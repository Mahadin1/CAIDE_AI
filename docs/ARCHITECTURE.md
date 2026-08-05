# DataScope — Adaptive EDA Platform Architecture

This document describes the redesign of the DataScope automated EDA system
into a professional, adaptive platform. It is the canonical reference for how
the system works and why it is built this way. Read this before touching the
backend.

---

## 1. Design principles

1. **pandas computes, rules decide, LLM only narrates (and plans).**
   Every number in a report is produced by deterministic code (pandas, scipy,
   statsmodels, numpy). The LLM never sees raw data — it sees a *data
   fingerprint* when planning and the *computed findings* when writing
   narrative prose. A broken or absent LLM must never produce a wrong number;
   it may only reduce the eloquence of the report.
2. **Adaptive, not a fixed checklist.** A small LLM-driven *planning* step
   reads a compact fingerprint of the data and emits an analysis plan. The
   executor then runs the plan deterministically. If planning fails, a fully
   deterministic fallback plan is used, so the system is always robust.
3. **Everything is explainable.** Every finding carries its method, the
   evidence (statistic + threshold), an interpretation, and an action the user
   could take. The narrative is written to read like a senior analyst
   walking through the data.
4. **Jobs are asynchronous.** `/analyze` returns immediately with a `job_id`.
   A background worker advances the job through explicit stages that the
   frontend polls. No hung requests, no request-scoped compute.
5. **Large data is handled transparently.** Files that are too big for a full
   in-memory analysis are either (a) read in chunks with online/streaming
   statistics, or (b) analyzed on a deterministic random sample. Every report
   states exactly what was done, on how many rows, and with what confidence.
6. **Determinism where possible.** Statistical computation is fully
   deterministic. Sampling uses a fixed seed derived from the file path, so
   re-running the same file produces the same sample and the same numbers.
   LLM output is the only non-deterministic part and it is cached per plan.

---

## 2. System overview

```
 Browser
   │  upload (simple ≤50 MiB, resumable TUS >50 MiB)
   ▼
 Supabase Storage (uploads/<user_id>/<file>)          ── frontend talks to this directly
   │
   │ POST /analyze {upload_id, storage_path, overrides}
   ▼
 FastAPI backend
   │  ● validate ownership + quota (synchronous, returns job_id)
   │  ● insert uploads row (status=pending, stage=queued)
   │  ● push job onto in-process asyncio worker queue
   ▼
 EDA worker (asyncio task, single consumer, recoverable)
   │  stages: loading → profiling → planning → computing →
   │          findings → narrating → persisting (status=done) / failed
   │
   ├─ eda/loader.py       format sniff + encoding detect + load (csv/tsv/xls/xlsx/json/parquet/feather)
   ├─ eda/sampling.py     decide mode (full|sample|streamed) + deterministic sample
   ├─ eda/streaming.py    Welford mean/var/skew, top-k sketch, exact missing counts (chunked reads)
   ├─ eda/fingerprint.py  compact, LLM-safe data profile
   ├─ eda/planner.py      LLM: fingerprint → analysis plan  (fallback = rule plan)
   ├─ eda/classification.py  column kind classification
   ├─ eda/stats_core.py   backbone statistics (deterministic)
   ├─ eda/tests.py        normality, ANOVA/Kruskal-Wallis, Spearman sig., Mann-Kendall, VIF, Little's MCAR
   ├─ eda/text.py         free-text handling (word/ngram counts)
   ├─ eda/dates.py        temporal feature extraction + seasonality
   ├─ eda/charts.py       declarative chart specs + drill-down metadata
   ├─ eda/findings.py     rule-based findings (method+evidence+interpretation+action)
   └─ eda/narrator.py     LLM: plan + findings → deep narrative (fallback prose)
   │
   ▼
 Supabase Postgres
   ├─ uploads  (job state: status, stage, error, attempts, plan, overrides, sample info)
   └─ reports  (summary_json, narrative, plan, sample info, export URLs)
```

**Why an in-process asyncio worker and not Celery?** The runtime does not
ship Redis/Celery. The worker is therefore an `asyncio.Queue` consumed by a
single background task started from the FastAPI lifespan. The worker interface
is a small `queue.py` module with a Celery-compatible contract
(`submit_job(job_id)`, `get_status(job_id)`); swapping to Celery/BullMQ later
only requires re-implementing that module, nothing else. On startup the worker
recovers interrupted jobs (see §7).

---

## 3. Job model, stages and progress

The `uploads` table **is** the job record (one upload = one job = at most one
report). Status lifecycle:

```
pending ──► processing ──► done
              │
              └──────────► failed
```

Progress is tracked with `stage` + `stage_label` (human text) + `progress`
(0–100, set by the worker). Stages:

| stage        | progress | work                                                        |
|--------------|----------|-------------------------------------------------------------|
| queued       | 5        | waiting in the worker queue                                 |
| loading      | 15       | download from storage, sniff format, detect encoding, parse |
| profiling    | 30       | fingerprint: rows/cols/memory/dtypes/kind hints/samples     |
| planning     | 40       | LLM plan from fingerprint (or deterministic fallback)       |
| computing    | 70       | backbone stats + plan-driven analyses (pandas/scipy/…)      |
| findings     | 85       | rule-based findings with evidence/interpretation/action     |
| narrating    | 90       | LLM narrative from plan + findings (or fallback prose)      |
| persisting   | 100      | write report, mark done, increment quota                    |

`error_message` stores a user-friendly, actionable message on failure. Raw
tracebacks are logged server-side only, never returned to the client.

**Retries & timeouts.** Transient failures (storage timeouts, OpenRouter
5xx/429, network blips) retry up to `JOB_MAX_ATTEMPTS` (default 3) with
exponential backoff, incrementing `attempts`. Permanent failures (unparseable
file, wrong format, RLS/quota, memory errors) fail immediately with a clear
message. An overall job timeout (`JOB_TIMEOUT_SECONDS`, default 900) cancels
hung jobs via `asyncio.wait_for`; blocking pandas work runs in a thread
executor so cancellation is possible. On startup, `pending` jobs are requeued
and `processing` jobs older than `JOB_STALE_SECONDS` are failed with a
"service restarted" message.

---

## 4. File loading (eda/loader.py)

Supported formats: CSV, TSV, Excel (.xls/.xlsx/.ods), JSON (array of objects
or newline-delimited), Parquet, Feather/Arrow.

- **Format sniffing ignores the extension.** A short magic-byte + content
  probe decides: `PK\x03\x04` → xlsx, `\xD0\xCF\x11\xE0` → xls (OLE2),
  `PAR1` → parquet, `ARROW1` → feather, `{`/`[` after whitespace → JSON,
  else tab/`,`/`;` delimited text → TSV/CSV/SEMICOLON. Delimiter is detected
  by counting candidate delimiters on the first sample lines.
- **Encoding detection** uses `charset_normalizer` (already vendored). UTF-8
  (with BOM handling) is assumed unless the detector disagrees; pandas
  `errors="replace"` is never used silently — if replacement characters are
  present a warning is recorded in the report.
- **Excel**: reads via `openpyxl` (xlsx) / `xlrd` (xls) / `odf` (ods). Excel
  row-count caps are enforced (see §6).
- **JSON**: array-of-objects is loaded directly; NDJSON (one object per line)
  is read line-by-line.
- **Parquet/Feather**: loaded with pyarrow; parquet row/column metadata is
  used for early size decisions without loading data.
- Errors are converted to `FriendlyError` with `user_message` + `kind`
  (e.g. `bad_csv`, `bad_excel`, `empty_file`, `unsupported_format`). The API
  layer turns these into 422 responses with the friendly message. Empty files,
  all-header files and files that fail to parse all produce actionable errors.

## 5. Large-data strategy (eda/sampling.py, eda/streaming.py)

The hard platform reality: **Supabase Storage rejects simple uploads above
50 MiB** (413 `EntityTooLarge`, verified empirically — 52,428,800 bytes
succeeds, 52,428,801 fails). The platform default applies even when the
bucket's `file_size_limit` is NULL. Therefore:

- **≤ 50 MiB**: browser simple upload (unchanged).
- **> 50 MiB**: the frontend switches to Supabase's **resumable (TUS)
  upload** (`duplex: 'half'`), which raises the ceiling to the plan's storage
  quota. The backend is unchanged for this path — it still downloads via a
  signed URL / service key.

**Backend analysis mode** is chosen automatically from the file after the
first profile pass:

| condition                                        | mode     | behaviour                                                          |
|--------------------------------------------------|----------|--------------------------------------------------------------------|
| rows ≤ 1,000,000 and cols ≤ 500                  | `full`   | exact stats on the whole frame                                     |
| rows > 1,000,000                                 | `sample` | deterministic random sample (seed = sha1(storage_path), target ≤ 200k rows) for detailed analyses; exact global aggregates from the streaming pass |
| cols > 500                                       | `truncated` | keep the first 500 columns, note the exclusion, sample mode if rows still huge |

`sample_info_json` in the report always states: `mode`, `total_rows`,
`sample_rows`, `sampled_fraction`, the sampling method, the seed, and a
**margin of error / confidence** for proportions (standard 95% CI,
`1.96*sqrt(p(1-p)/n)`, worst-case `p=0.5` bound included). Reports explicitly
label every number produced from the sample vs. exact global aggregates.

**Streaming pass (eda/streaming.py).** Whenever we read a CSV/TSV in chunks we
accumulate exact, mergeable aggregates regardless of sampling:

- **Welford's method** for mean, variance, skew, kurtosis per numeric column
  (stable, single pass, no floating-point blowup).
- exact **missing counts**, **row count**, and **column count**;
- a capped **top-K frequency sketch** (dict, capped at 10k entries) per
  categorical column, so top-value charts are exact for high-frequency values
  even when the detailed analysis runs on a sample.

Correlations, crosstabs, outlier detection and statistical tests are *not*
stream-mergeable cheaply, so those run on the (deterministic) sample and are
labelled as sample-based. This is the "Option A + Option B hybrid" — exact
globals via streaming, deep analytics via sampling, and full transparency in
the report.

## 6. Hard limits (performance & abuse protection)

| limit | value | enforced at | behaviour |
|-------|-------|-------------|-----------|
| max rows for full analysis | 1,000,000 | worker | switch to `sample` mode |
| max columns | 500 | worker | truncate + note in report |
| max Excel sheet rows loaded | 1,048,576 | loader | sample within the loader |
| max JSON objects | 1,000,000 | loader | stop + sample note |
| job timeout | 900 s | worker | cancel + fail |
| max attempts | 3 | worker | transient-retry budget |
| CSV chunk size | 200,000 rows | streaming | bounded memory |

All limits are configurable in `config.py`.

## 7. Adaptive planning (eda/fingerprint.py, eda/planner.py)

**Fingerprint** (what the LLM is allowed to see): `{format, rows, columns,
memory_bytes, is_sample, columns: [{name, dtype, kind_hint, cardinality,
missing_pct, numeric_pct, date_pct, text_avg_words, samples[3]}]}`. No raw
values beyond 3 example cells, no full distributions. Compact and safe.

**Planner** asks the LLM (single call, low temperature) for a JSON list of
tasks. Each task: `{id, type, description, rationale, target_columns[],
enabled}`. The allowed task types are the closed set the executor knows how to
run deterministically:

```
missing_pattern | outlier_multimethod | normality | distribution_fit |
anova_kruskal | spearman_sig | cramer_v | vif | trend_mannkendall |
time_features | seasonality | duplicate_ids | date_as_text |
mixed_type_cleanup | text_top_words | group_comparison |
cardinality_sanity | custom_question
```

Robust JSON parsing strips markdown fences; on any parse/API failure the
**deterministic fallback plan** is used (see below). The plan is stored in
`uploads.analysis_plan_json` / `reports.analysis_plan_json` so re-renders are
consistent and the plan is cached (a re-run with identical fingerprint +
overrides reuses the stored plan without a second LLM call).

**Executor.** The backbone (classification + all base statistics, §8) always
runs. The *conditional/expensive* analyses are run only when the plan asks for
them (or when cheap data conditions strongly imply them in fallback mode).
Every executed task records `{task, rationale, method, result, interpretation,
action}` in the summary, so the narrative can explain *why each analysis was
chosen* — or skipped.

**Deterministic fallback plan**: if the LLM is unavailable/misconfigured, the
planner emits the same plan every time, built by cheap data conditions (has
numeric columns → normality/outliers/skew/spearman; ≥2 numeric → VIF +
correlations; categorical + numeric → ANOVA; date-like → trend + seasonality;
high-cardinality text → text_top_words; etc.). This preserves a comprehensive,
non-boring report with zero LLM dependence.

## 8. Statistics backbone (eda/stats_core.py, eda/classification.py)

Unchanged semantics from the original system, reorganized into modules:

- `classification.py` — column kinds: `constant`, `numeric`, `date_like`,
  `mixed`, `identifier`, `empty`, `categorical`, plus **new** kinds
  `free_text` (avg word count > 5 or very high cardinality → text analysis
  instead of category charts) and `boolean`.
- `stats_core.py` — describe/skew, Pearson correlations, IQR outliers, missing
  counts/%, duplicate rows, categorical top values, histograms,
  numeric-by-category comparisons, Cramér's V, time trends.

## 9. Enhanced analyses (eda/tests.py, eda/text.py, eda/dates.py)

These run when the plan asks (or fallback conditions recommend):

- **Missing data**: missing-pair correlation, and **Little's MCAR test**
  (chi-square based) with interpretation (MCAR / MAR / MNAR). Missingness
  "by other columns" is summarised as per-column means under missing vs present.
- **Outliers**: IQR (backbone) + **Z-score** (robust MAD-based, ±3.5) and an
  **Isolation Forest** pass when `sklearn` is installed; each method explains
  why it was chosen and how its result differs.
- **Distributions**: Shapiro-Wilk (n ≤ 5000, otherwise D'Agostino's K²),
  plus suggested fitted distribution (Gaussian, lognormal, gamma, exponential)
  via scipy and a log-likelihood ranking.
- **Statistical tests**: ANOVA + **Kruskal-Wallis** (with post-hoc pairwise
  differences via Tukey-HSD fallback to Mann-Whitney), Pearson vs **Spearman**
  with p-values and a significance flag, **Mann-Kendall** trend test on date
  series, **VIF** for multicollinearity, Cramér's V with p-value.
- **Text columns**: average words, vocabulary size, top words/ngrams
  (word-cloud data), length distribution; category-style charts are skipped
  with a clear note.
- **Dates**: temporal features (year, month, weekday, hour), month-of-year
  seasonality profile (deviations from the row-count mean), trend strength.

## 10. Findings, narrative and exports

**findings.py** produces structured findings — always including `method`,
`evidence` (statistic + threshold used), `interpretation` (plain language),
and `action` (what the user could do). `charts.py` emits declarative
`chart_specs` with optional `drill_down` metadata (`{column, filter_value,
route}`) so the frontend can offer "view the rows behind this bar".

**narrator.py** — one LLM call: system prompt is a "senior analyst walking a
stakeholder through the data" persona; the user message carries
`{plan, findings, overview}` (all computed, no raw data). The result must be
plain prose, several paragraphs, ≤ 1200 words. On any failure a deterministic
long-form narrative is assembled from the findings' `interpretation` +
`action` fields. The LLM is explicitly forbidden from inventing numbers.

**Export & sharing** (`export_html.py`, `pdf.py`):
- Self-contained HTML export: inline CSS + base64 PNG charts (matplotlib,
  rendered server-side from `summary_json`, never from the raw file), the full
  narrative, plan, findings and sample banner. One file, no external assets.
- PDF export (existing ReportLab path, extended with the new sections).
- Cleaned-data download: re-parse the source, apply the transformations the
  report recommended (strip, numeric coercion where clean, date parsing),
  stream as CSV.
- All three are Pro-gated and ownership-checked server-side. Export URLs are
  stored on the report row.

## 11. API surface

| endpoint | method | auth | purpose |
|----------|--------|------|---------|
| `/analyze` | POST | ownership+quota check | returns `{job_id}` immediately; accepts `overrides` |
| `/analyze/plan` | POST | ownership | synchronous fingerprint + proposed plan + editable type map |
| `/jobs/{upload_id}` | GET | ownership | `{status, stage, stage_label, progress, error_message, report_id}` |
| `/reports/{id}/export/html` | GET | ownership + Pro | self-contained HTML |
| `/reports/{id}/export/pdf` | GET | ownership + Pro | PDF (existing) |
| `/reports/{id}/download/clean` | GET | ownership + Pro | cleaned CSV |
| `/reports/{id}/subset?column=&value=` | GET | ownership + Pro | ≤500 rows behind a chart bar |
| `/health` | GET | — | liveness |

All endpoints are proxied through Next.js route handlers (`/api/...`) so the
browser never needs the backend's internal URL and identity comes from the
session cookie.

## 12. Schema extensions (db/schema.sql)

`uploads` adds: `file_size_bytes bigint`, `source_format text`,
`detected_encoding text`, `analysis_mode text`, `analysis_plan_json jsonb`,
`overrides_json jsonb`, `stage text default 'queued'`, `stage_label text`,
`progress int default 5`, `error_message text`, `attempts int default 0`,
`row_estimate bigint`, `column_count int`.

`reports` adds: `analysis_plan_json jsonb`, `overrides_json jsonb`,
`sample_info_json jsonb`, `analysis_mode text`, `source_format text`,
`export_html_url text`, `export_pdf_url text`, `cleaned_data_url text`.

RLS and quota behaviour are unchanged.

## 13. Determinism & caching

- Sampling seed = `sha1(storage_path)` → same file, same sample.
- The LLM plan is cached keyed by `(fingerprint_hash, overrides_hash)`.
- Statistical output is fully deterministic given the loaded data.
- The narrative is the only non-deterministic output; it is persisted once and
  never regenerated in place.

## 14. Configuration (config.py)

All new knobs live in `Settings` with env overrides:

```
JOB_TIMEOUT_SECONDS=900        JOB_MAX_ATTEMPTS=3
JOB_STALE_SECONDS=1800         MAX_ROWS_FULL=1000000
MAX_COLUMNS=500                SAMPLE_TARGET_ROWS=200000
CSV_CHUNK_SIZE=200000          ANALYSIS_MODEL=<openrouter model>
NARRATIVE_MAX_WORDS=1200
```

## 15. Implementation plan (build order)

1. Schema migration (§12) + apply live.
2. `eda/loader.py`, `eda/streaming.py`, `eda/sampling.py` (+ fingerprint).
3. `eda/classification.py`, `eda/stats_core.py` (move from `agent.py`).
4. `eda/tests.py`, `eda/text.py`, `eda/dates.py`, `eda/charts.py`.
5. `eda/planner.py`, `eda/findings.py`, `eda/narrator.py`.
6. `worker.py` + `queue.py`; rewrite `main.py` endpoints.
7. `export_html.py`, extend `pdf.py`, clean-download.
8. Apply schema, install deps, restart, end-to-end verify.
9. Frontend: multi-format upload, resumable upload >50 MiB, plan preview +
   overrides, job progress view, sample banner, drill-down, export buttons.
10. Developer docs (this document + module docstrings).

## 16. Key risks & mitigations

- **LLM free-tier flakiness** → planner & narrator both fall back to fully
  deterministic equivalents; the report is always produced.
- **50 MiB storage ceiling** → TUS resumable uploads on the frontend; backend
  unchanged.
- **Memory on huge files** → chunked streaming + deterministic sampling; the
  raw bytes are spooled to a tempfile instead of RAM above 100 MB.
- **Cancellation of blocking compute** → all heavy work runs through
  `asyncio.to_thread`; job-level timeout cancels the surrounding coroutine and
  the thread is left to finish detached (bounded by pandas' own behaviour).
- **Schema drift** → the migration is idempotent `alter table ... add column
  if not exists`.
