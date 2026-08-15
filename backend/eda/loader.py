"""Multi-format file loading with format sniffing and encoding detection.

Supported: CSV, TSV, semicolon-delimited text, Excel (.xls/.xlsx/.ods), JSON
(array of objects or NDJSON), Parquet, Feather/Arrow.

The loader is deliberately format-first and extension-second: magic bytes and
content probes decide what a file actually is, so a `.csv` that is really a
parquet file, or a `.txt` that is really JSON, is handled correctly.

Large text files are read in chunks. Two loading strategies exist:

  * full load   — when the row estimate is within `max_rows_full`, the whole
                  file is read into memory and all statistics are exact;
  * sampled     — otherwise a two-pass read happens: pass 1 counts rows and
                  accumulates a :class:`StreamingSummary` (exact globals),
                  pass 2 takes a deterministic, position-stratified random
                  sample of `sample_target` rows for the detailed analyses.

See docs/ARCHITECTURE.md §4–§5.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np
import pandas as pd
from charset_normalizer import from_bytes as charset_from_bytes

from eda.errors import FriendlyError
from eda.streaming import StreamingSummary

SPOOL_THRESHOLD = 100 * 1024 * 1024  # 100 MiB — beyond this, spool to disk
_TEXT_FORMATS = {"csv", "tsv", "semicolon"}
SUPPORTED_EXTENSIONS = {
    ".csv", ".tsv", ".txt", ".xls", ".xlsx", ".ods",
    ".json", ".jsonl", ".ndjson", ".parquet", ".feather", ".arrow",
}


@dataclass
class LoadedData:
    """Everything the pipeline needs to know about the parsed file."""

    df: pd.DataFrame
    fmt: str
    encoding: str | None
    sep: str | None = None
    temp_path: str | None = None
    total_rows: int = 0            # exact when fully_loaded, else exact via streaming
    fully_loaded: bool = True
    truncated_cols: list[str] = field(default_factory=list)
    streaming: StreamingSummary | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int]:
        return self.df.shape


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _peek(data: bytes, n: int = 4096) -> bytes:
    return data[:n]


def _read_file_head(path: str, n: int) -> bytes:
    """Read the first ``n`` bytes of a spooled file (for detection)."""
    with open(path, "rb") as fh:
        return fh.read(n)


def detect_format(data: bytes, filename: str = "") -> str:
    """Identify the actual file format from content (not extension)."""
    head = _peek(data)
    ext = os.path.splitext(filename or "")[1].lower()

    # Excel 2007+ / OOXML (zip container, PK header).
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        if ext in (".xls", ".xlsx", ".ods"):
            if ext == ".ods":
                return "ods"
            return "xlsx"
        # A zip that isn't a recognised spreadsheet — try xlsx and let the
        # loader raise a friendly error if it isn't.
        return "xlsx"
    # Excel 97-2003 binary (OLE2 container).
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    # Parquet and Feather magic bytes.
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"ARROW1"):
        return "feather"

    # Text-based: strip a UTF-8 BOM and leading whitespace.
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        # NDJSON vs array-of-objects vs JSON Lines.
        return "json"
    if stripped.startswith(b"\x00"):
        raise FriendlyError(
            "This file does not look like a supported data format "
            "(CSV, TSV, Excel, JSON, Parquet or Feather).",
            kind="unsupported",
        )
    return "csv"  # text table — delimiter sniffing happens next


def sniff_delimiter(data: bytes | None = None, path: str | None = None) -> str:
    """Pick the delimiter from a sample of text lines.

    Tabs are preferred when they are consistent, otherwise the most frequent
    of `,` and `;` outside double quotes wins.
    """
    try:
        if data is not None:
            sample = data[:64 * 1024].decode("utf-8", errors="replace")
        else:
            sample = _read_file_head(path or "", 64 * 1024).decode(
                "utf-8", errors="replace"
            )
    except Exception:
        return ","
    lines = [ln for ln in sample.splitlines() if ln.strip()][:50]
    if not lines:
        return ","
    candidate_lines = [re.split(r'("(?:[^"]|"")*")', ln) for ln in lines]
    counts = {",": 0, ";": 0, "\t": 0}
    for parts in candidate_lines:
        # Re-join so we only count delimiters outside quotes.
        outside = "".join(parts[0::2])
        for delim in counts:
            counts[delim] += outside.count(delim)
    # Tabs are rarely ambiguous; prefer them if any line splits into >=2 fields.
    if all("\t" in ln for ln in lines[:10]):
        return "\t"
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return ","
    if best == "\t":
        return "\t"
    if best == ";":
        return ";"
    return ","


def detect_encoding(data: bytes | None = None, path: str | None = None) -> str:
    """Best-effort encoding detection with a UTF-8 default."""
    if data is not None:
        sample = _peek(data, 20000)
    else:
        sample = _read_file_head(path or "", 20000)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    result = charset_from_bytes(sample).best()
    if result is None:
        return "utf-8"
    return result.encoding or "utf-8"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _spool(data: bytes) -> str:
    fd, path = tempfile.mkstemp(prefix="datascope-", suffix=".bin")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def _text_source(data: bytes, temp_path: str | None):
    if temp_path is not None:
        return temp_path
    return io.BytesIO(data)


def _cleanup_temp(temp_path: str | None) -> None:
    if temp_path:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _read_text(
    source: Any,
    sep: str,
    encoding: str,
    chunksize: int | None = None,
    dtype_map: dict[str, str] | None = None,
) -> pd.DataFrame | Iterator[pd.DataFrame]:
    kwargs: dict[str, Any] = {
        "sep": sep,
        "encoding": encoding,
        "on_bad_lines": "error",
        "dtype": dtype_map,
        "low_memory": False,
    }
    if chunksize:
        kwargs["chunksize"] = chunksize
        return pd.read_csv(source, **kwargs)
    return pd.read_csv(source, **kwargs)


def _read_text_safe(
    data: bytes,
    temp_path: str | None,
    sep: str,
    encoding: str,
    fmt: str,
) -> pd.DataFrame:
    """Read a text table, mapping pandas' various errors to friendly ones."""
    source = _text_source(data, temp_path)
    try:
        return pd.read_csv(
            source, sep=sep, encoding=encoding, on_bad_lines="error",
            low_memory=False,
        )
    except UnicodeDecodeError as exc:
        raise FriendlyError(
            "The file could not be decoded cleanly. Try re-saving it as "
            "UTF-8, or convert it to CSV in a spreadsheet program.",
            kind="bad_csv",
        ) from exc
    except pd.errors.ParserError as exc:
        raise FriendlyError(
            "The file is not well-formed tabular text: rows have different "
            "numbers of columns, or quoting is broken. Check for stray "
            "quotes or unescaped delimiters.",
            kind="bad_csv",
        ) from exc
    except pd.errors.EmptyDataError as exc:
        raise FriendlyError("The file contains no data rows.", kind="empty_file") from exc


def _load_json(
    data: bytes | None, encoding: str, max_rows: int, path: str | None = None
) -> pd.DataFrame:
    if data is None:
        with open(path or "", "rb") as fh:
            data = fh.read()
    try:
        text = data.decode(encoding or "utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to NDJSON (one object per line).
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise FriendlyError(
                    "This JSON file is neither an array of objects nor "
                    "line-delimited JSON objects.",
                    kind="bad_json",
                ) from None
            if not isinstance(record, dict):
                raise FriendlyError(
                    "JSON entries must be objects (key/value pairs).",
                    kind="bad_json",
                )
            records.append(record)
        obj = records

    if isinstance(obj, dict):
        # Tolerate a wrapping key ("data", "results", "items") holding the array.
        for key in ("data", "results", "items", "rows"):
            if isinstance(obj.get(key), list) and obj[key]:
                obj = obj[key]
                break
    if not isinstance(obj, list):
        raise FriendlyError(
            "JSON input must be an array of objects.",
            kind="bad_json",
        )
    if len(obj) > max_rows:
        obj = obj[:max_rows]
    if obj and not all(isinstance(r, dict) for r in obj):
        raise FriendlyError("JSON entries must be objects (key/value pairs).", kind="bad_json")
    if not obj:
        raise FriendlyError("The JSON file contains no records.", kind="empty_file")
    return pd.json_normalize(obj)


def _load_excel(data: bytes, temp_path: str | None, fmt: str) -> pd.DataFrame:
    source = _text_source(data, temp_path)
    engine = {"xlsx": "openpyxl", "xls": "xlrd", "ods": "odf"}[fmt]
    try:
        df = pd.read_excel(source, engine=engine, sheet_name=0)
    except FriendlyError:
        raise
    except Exception as exc:
        raise FriendlyError(
            "The spreadsheet could not be read. Open it in Excel/Sheets and "
            "re-save it as .xlsx, or export the sheet to CSV.",
            kind="bad_excel",
        ) from exc
    if df is None or df.empty:
        raise FriendlyError("The spreadsheet contains no data.", kind="empty_file")
    return df


def _estimate_text_rows(
    data: bytes, temp_path: str | None, sep: str, encoding: str
) -> int:
    """Fast newline-based row estimate for text tables (used for the
    full-vs-sample decision before loading everything)."""
    try:
        if temp_path is not None:
            size = os.path.getsize(temp_path)
            with open(temp_path, "rb") as fh:
                sample = fh.read(min(size, 512 * 1024))
        else:
            sample = data[:512 * 1024]
        text = sample.decode(encoding or "utf-8", errors="replace")
        newlines = text.count("\n")
        if newlines <= 1:
            return 0
        total = len(data) if temp_path is None else os.path.getsize(temp_path)
        if len(sample) < total:
            ratio = total / len(sample)
            return int(newlines * ratio)
        return newlines
    except Exception:
        return 0


def _two_pass_sample(
    data: bytes,
    temp_path: str | None,
    sep: str,
    encoding: str,
    target_rows: int,
    seed: int,
    chunksize: int,
) -> tuple[pd.DataFrame, int, StreamingSummary, dict[str, str]]:
    """Pass 1: count rows + streaming aggregates. Pass 2: deterministic
    position-stratified sample of `target_rows`. Returns (sample, total_rows,
    streaming, dtype_map_from_first_chunk)."""
    streaming = StreamingSummary()
    dtype_map: dict[str, str] = {}
    total = 0

    src = _text_source(data, temp_path)
    iterator = _read_text(src, sep, encoding, chunksize=chunksize)
    for chunk in iterator:
        if not dtype_map:
            dtype_map = {c: str(t) for c, t in chunk.dtypes.items()}
        else:
            chunk = chunk.astype(dtype_map)
        streaming.add_chunk(chunk)
        total += int(len(chunk))
    if total == 0:
        raise FriendlyError("The file contains no data rows.", kind="empty_file")

    if total <= target_rows:
        # The estimate was pessimistic — the file is actually small. Re-read
        # it fully (cheaper than keeping every row in memory during pass 1).
        sample = _read_text_safe(data, temp_path, sep, encoding, "csv")
        return sample, total, streaming, dtype_map

    rng = np.random.default_rng(seed)
    src2 = _text_source(data, temp_path)
    iterator2 = _read_text(src2, sep, encoding, chunksize=chunksize, dtype_map=dtype_map)
    parts: list[pd.DataFrame] = []
    for chunk in iterator2:
        n = len(chunk)
        take = max(1, int(round(n / total * target_rows)))
        parts.append(chunk.sample(n=min(n, take), random_state=rng, ignore_index=True))
    sample = pd.concat(parts, ignore_index=True)
    # Trim to the target in case rounding overshot.
    if len(sample) > target_rows:
        sample = sample.sample(n=target_rows, random_state=rng, ignore_index=True)
    return sample, total, streaming, dtype_map


def load_dataframe(
    data: bytes | None,
    filename: str = "",
    *,
    path: str | None = None,
    max_rows_full: int = 1_000_000,
    sample_target: int = 200_000,
    seed: int | None = None,
    max_cols: int = 500,
) -> LoadedData:
    """Load a file into a DataFrame, deciding full-vs-sample.

    ``data`` carries the file as in-memory bytes (small files). Alternatively
    ``path`` points at a spooled copy on disk (large downloads) — the loader
    then reads detection samples and streaming chunks straight from the file
    and never materialises the full bytes. Exactly one of ``data``/``path``
    must be provided. ``temp_path`` on the returned :class:`LoadedData`
    references ``path`` when given, so cleanup_loaded() removes it.

    Raises :class:`FriendlyError` for malformed/unsupported/empty files.
    """
    if data is None and path is None:
        raise FriendlyError("The file is empty.", kind="empty_file")
    head = data[:4096] if data is not None else _read_file_head(path or "", 4096)
    if not head:
        raise FriendlyError("The file is empty.", kind="empty_file")

    fmt = detect_format(head, filename)
    temp_path: str | None = path
    if data is not None and len(data) > SPOOL_THRESHOLD and fmt in _TEXT_FORMATS:
        temp_path = _spool(data)

    try:
        encoding: str | None = None
        sep: str | None = None
        warnings: list[str] = []

        if fmt in _TEXT_FORMATS:
            encoding = detect_encoding(data, path)
            sep = sniff_delimiter(data, path)
            if fmt == "tsv" and sep != "\t":
                sep = "\t"
            if fmt == "csv":
                # Re-sniff: extension may have lied about the delimiter.
                detected = sniff_delimiter(data, path)
                if detected == "\t":
                    fmt, sep = "tsv", "\t"
                elif detected == ";":
                    sep = ";"
            if sep == "\t":
                fmt = "tsv"

            estimate = _estimate_text_rows(data, temp_path, sep, encoding)
            if estimate > max_rows_full:
                seed_int = seed if seed is not None else 0
                sample, total, streaming, _ = _two_pass_sample(
                    data, temp_path, sep, encoding, sample_target, seed_int,
                    chunksize=200_000,
                )
                loaded = LoadedData(
                    df=sample,
                    fmt=fmt,
                    encoding=encoding,
                    sep=sep,
                    temp_path=temp_path,
                    total_rows=total,
                    fully_loaded=False,
                    streaming=streaming,
                    warnings=warnings,
                )
                return _truncate_columns(loaded, max_cols)

            df = _read_text_safe(data, temp_path, sep, encoding, fmt)
            if df.empty:
                raise FriendlyError("The file contains no data rows.", kind="empty_file")

        elif fmt == "json":
            encoding = detect_encoding(data, path)
            df = _load_json(data, encoding, max_rows_full, path)

        elif fmt in ("xlsx", "xls", "ods"):
            encoding = None
            df = _load_excel(data, temp_path, fmt)

        elif fmt == "parquet":
            try:
                df = pd.read_parquet(_text_source(data, temp_path))
            except Exception as exc:
                raise FriendlyError(
                    "The Parquet file could not be read; it may be corrupt "
                    "or use an unsupported codec.",
                    kind="bad_parquet",
                ) from exc

        elif fmt == "feather":
            try:
                df = pd.read_feather(_text_source(data, temp_path))
            except Exception as exc:
                raise FriendlyError(
                    "The Feather file could not be read; it may be corrupt.",
                    kind="bad_parquet",
                ) from exc

        else:  # pragma: no cover
            raise FriendlyError("Unsupported file format.", kind="unsupported")

        if df.empty:
            raise FriendlyError("The file contains no data rows.", kind="empty_file")

        loaded = LoadedData(
            df=df, fmt=fmt, encoding=encoding, sep=sep, temp_path=temp_path,
            total_rows=int(len(df)), fully_loaded=True, warnings=warnings,
        )
        return _truncate_columns(loaded, max_cols)

    except FriendlyError:
        _cleanup_temp(temp_path)
        raise
    except MemoryError:
        _cleanup_temp(temp_path)
        raise FriendlyError(
            "The file is too large to analyze in memory. Try a smaller file "
            "or trim it to the columns you need.",
            kind="out_of_memory",
        ) from None
    except Exception as exc:
        _cleanup_temp(temp_path)
        if isinstance(exc, FriendlyError):
            raise
        raise FriendlyError(
            "The file could not be analyzed. If it is a spreadsheet, try "
            "re-saving it as CSV and uploading again.",
            kind="bad_file",
        ) from exc


def _truncate_columns(loaded: LoadedData, max_cols: int) -> LoadedData:
    if loaded.df.shape[1] > max_cols:
        keep = loaded.df.columns[:max_cols]
        loaded.truncated_cols = [str(c) for c in loaded.df.columns[max_cols:]]
        loaded.df = loaded.df[keep]
        loaded.warnings.append(
            f"The file has more than {max_cols} columns; only the first "
            f"{max_cols} were analyzed."
        )
    return loaded


def iter_text_chunks(
    data: bytes,
    temp_path: str | None,
    sep: str,
    encoding: str,
    chunksize: int = 200_000,
) -> Iterator[pd.DataFrame]:
    """Stream a text table in chunks (used for cleaned-data export)."""
    source = _text_source(data, temp_path)
    yield from _read_text(source, sep, encoding, chunksize=chunksize)


def cleanup_loaded(loaded: LoadedData) -> None:
    _cleanup_temp(loaded.temp_path)
