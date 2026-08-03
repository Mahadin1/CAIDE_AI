"""Server-side PDF export for Pro reports.

Uses ReportLab (pure Python, no system Chromium, no new dependency beyond
what was already in requirements.txt) to render the narrative, a set of
real charts, and tables of the key computed statistics.

Everything charted here comes straight from `summary` (produced by
agent.run_eda) — this module never recomputes a statistic and never
touches the original DataFrame, so a PDF can never show a number that
disagrees with the narrative or the stored summary_json.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BORDER = colors.HexColor("#232A33")
MUTED = colors.HexColor("#8A94A3")
ACCENT = colors.HexColor("#00D4FF")
ACCENT_DIM = colors.HexColor("#7FE6FF")
TEXT = colors.HexColor("#0B0E11")

# ---------------------------------------------------------------------------
# Chart caps and thresholds.
#
# The threshold values below intentionally mirror the constants of the same
# name in agent.py (GROUP_DIFFERENCE_MIN_EFFECT, CRAMERS_V_ASSOCIATION_
# THRESHOLD, TREND_CORR_THRESHOLD) so the PDF never charts something the
# narrative considers unremarkable, or vice versa. They're duplicated
# locally rather than imported so this module has no import-time
# dependency on agent.py (and, transitively, on config/httpx).
# ---------------------------------------------------------------------------
MAX_HISTOGRAM_CHARTS = 6
MAX_CATEGORY_CHARTS = 4
MAX_GROUP_COMPARISON_CHARTS = 3
MAX_ASSOCIATION_ROWS = 5
MAX_TREND_CHARTS = 3
MAX_CORRELATION_BAR_PAIRS = 5

GROUP_DIFFERENCE_MIN_EFFECT = 0.5
CRAMERS_V_ASSOCIATION_THRESHOLD = 0.3
TREND_CORR_THRESHOLD = 0.5
MIN_CORRELATION_TO_CHART = 0.3

NON_CHARTABLE_CLASSIFICATION_KINDS = {"date_like", "mixed", "identifier", "constant", "empty"}


def _styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "DSTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=TEXT,
        alignment=TA_LEFT,
        spaceAfter=2 * mm,
    )
    meta = ParagraphStyle(
        "DSMeta",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=MUTED,
        spaceAfter=6 * mm,
    )
    h2 = ParagraphStyle(
        "DSH2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=TEXT,
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    )
    body = ParagraphStyle(
        "DSBody",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=16,
        textColor=TEXT,
    )
    caption = ParagraphStyle(
        "DSCaption",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=MUTED,
        spaceAfter=2 * mm,
    )
    return title, meta, h2, body, caption


def _kv_table(rows: list[list[str]]) -> Table:
    # Available content width on an A4 page with 20mm side margins.
    content_width = A4[0] - 40 * mm
    ncols = len(rows[0]) if rows else 2
    first_col = 60 * mm
    other_col = (content_width - first_col) / max(ncols - 1, 1)
    widths = [first_col] + [other_col for _ in range(ncols - 1)]
    table = Table(rows, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), TEXT),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _fmt_num(x: float | None) -> str:
    if x is None:
        return "–"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 1:
        return f"{x:.1f}"
    return f"{x:.3g}"


def _truncate(label: Any, max_len: int = 12) -> str:
    label = str(label)
    return label if len(label) <= max_len else label[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Chart drawing (ReportLab graphics — no external chart/image library)
# ---------------------------------------------------------------------------

def _bar_chart(
    categories: list[str],
    values: list[float],
    title: str,
    width: float = 470,
    height: float = 170,
) -> Drawing:
    """A single-series vertical bar chart. Handles negative values (used
    for signed correlation bars) by letting the value axis dip below zero
    instead of clipping."""
    drawing = Drawing(width, height)
    if title:
        drawing.add(
            String(2, height - 10, title, fontName="Helvetica-Bold", fontSize=9, fillColor=TEXT)
        )

    chart = VerticalBarChart()
    chart.x = 45
    chart.y = 34
    chart.width = width - 65
    chart.height = height - 60
    chart.data = [values]
    chart.categoryAxis.categoryNames = [_truncate(c) for c in categories]
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.dx = -4
    chart.categoryAxis.labels.dy = -10
    chart.categoryAxis.labels.textAnchor = "end"

    lo = min(values) if values else 0
    hi = max(values) if values else 1
    rng = (hi - lo) or (abs(hi) or 1)
    chart.valueAxis.valueMin = lo - rng * 0.1 if lo < 0 else 0
    chart.valueAxis.valueMax = hi + rng * 0.15 if hi > 0 else 1
    chart.valueAxis.labels.fontSize = 7

    chart.bars[0].fillColor = ACCENT
    chart.bars[0].strokeColor = None
    chart.barSpacing = 2

    drawing.add(chart)
    return drawing


def _line_chart(
    categories: list[str],
    values: list[float],
    title: str,
    width: float = 470,
    height: float = 170,
) -> Drawing:
    """A single-series line chart for a time-ordered count series."""
    drawing = Drawing(width, height)
    if title:
        drawing.add(
            String(2, height - 10, title, fontName="Helvetica-Bold", fontSize=9, fillColor=TEXT)
        )

    chart = HorizontalLineChart()
    chart.x = 45
    chart.y = 34
    chart.width = width - 65
    chart.height = height - 60
    chart.data = [values]
    chart.categoryAxis.categoryNames = [_truncate(c, 10) for c in categories]
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.dx = -4
    chart.categoryAxis.labels.dy = -10
    chart.categoryAxis.labels.textAnchor = "end"

    hi = max(values) if values else 1
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = hi * 1.15 if hi > 0 else 1
    chart.valueAxis.labels.fontSize = 7

    chart.lines[0].strokeColor = ACCENT
    chart.lines[0].strokeWidth = 1.6

    drawing.add(chart)
    return drawing


# ---------------------------------------------------------------------------
# Report sections built from summary — each returns a list of flowables,
# and each returns [] (rather than raising) when it has nothing to show,
# so build_pdf never needs to know in advance what a given dataset has.
# ---------------------------------------------------------------------------

def _distribution_section(summary: dict[str, Any], h2, caption) -> list:
    histograms = summary.get("histograms") or {}
    if not histograms:
        return []
    story = [
        Paragraph("Distributions", h2),
        Paragraph(
            "Bar height shows how many rows fall into each value range.",
            caption,
        ),
    ]
    for col, hist in list(histograms.items())[:MAX_HISTOGRAM_CHARTS]:
        edges = hist.get("bin_edges") or []
        counts = hist.get("counts") or []
        if len(edges) < 2 or not counts:
            continue
        labels = [f"{_fmt_num(edges[i])}–{_fmt_num(edges[i + 1])}" for i in range(len(counts))]
        story.append(_bar_chart(labels, counts, f"Distribution of {col}"))
        story.append(Spacer(1, 3 * mm))
    return story if len(story) > 2 else []


def _category_section(summary: dict[str, Any], h2) -> list:
    classification = summary.get("column_classification", {})
    cat_summary = summary.get("categorical_summary") or {}
    entries = [
        (col, info)
        for col, info in cat_summary.items()
        if classification.get(col, {}).get("kind") not in NON_CHARTABLE_CLASSIFICATION_KINDS
        and info.get("top")
    ]
    if not entries:
        return []
    story = [Paragraph("Category breakdown", h2)]
    for col, info in entries[:MAX_CATEGORY_CHARTS]:
        labels = [t["value"] for t in info["top"]]
        values = [t["count"] for t in info["top"]]
        story.append(_bar_chart(labels, values, f"Top values of {col}"))
        story.append(Spacer(1, 3 * mm))
    return story


def _group_comparison_section(summary: dict[str, Any], h2, caption) -> list:
    comparisons = list((summary.get("numeric_by_categorical") or {}).items())
    comparisons.sort(key=lambda kv: abs(kv[1].get("effect_size_std") or 0), reverse=True)
    notable = [
        (k, c) for k, c in comparisons if abs(c.get("effect_size_std") or 0) >= GROUP_DIFFERENCE_MIN_EFFECT
    ]
    if not notable:
        return []
    story = [
        Paragraph("Group comparisons", h2),
        Paragraph(
            "Average value of a numeric column, broken down by category. "
            "A bigger gap between the tallest and shortest bar means a "
            "stronger relationship between the two columns.",
            caption,
        ),
    ]
    for _, cmp in notable[:MAX_GROUP_COMPARISON_CHARTS]:
        labels = [g["group"] for g in cmp["groups"]]
        values = [g["mean"] for g in cmp["groups"]]
        title = f"Average {cmp['numeric_column']} by {cmp['category_column']}"
        story.append(_bar_chart(labels, values, title))
        story.append(Spacer(1, 3 * mm))
    return story


def _association_section(summary: dict[str, Any], h2, caption) -> list:
    assoc = list((summary.get("categorical_associations") or {}).items())
    assoc.sort(key=lambda kv: kv[1].get("cramers_v") or 0, reverse=True)
    notable = [(k, a) for k, a in assoc if (a.get("cramers_v") or 0) >= CRAMERS_V_ASSOCIATION_THRESHOLD]
    if not notable:
        return []
    top = notable[:MAX_ASSOCIATION_ROWS]
    labels = [f"{a['column_a']} vs {a['column_b']}" for _, a in top]
    values = [round((a["cramers_v"] or 0) * 100, 1) for _, a in top]
    return [
        Paragraph("Categorical associations", h2),
        Paragraph(
            "Cramér's V measures how strongly two categorical columns move "
            "together, on a scale from 0 (unrelated) to 100 (perfectly related).",
            caption,
        ),
        _bar_chart(labels, values, "Association strength (Cramér's V × 100)"),
        Spacer(1, 3 * mm),
    ]


def _trend_section(summary: dict[str, Any], h2) -> list:
    trends = list((summary.get("time_trends") or {}).items())
    trends.sort(key=lambda kv: abs(kv[1].get("trend_correlation") or 0), reverse=True)
    notable = [
        (col, t)
        for col, t in trends
        if abs(t.get("trend_correlation") or 0) >= TREND_CORR_THRESHOLD and t.get("series")
    ]
    if not notable:
        return []
    story = [Paragraph("Trends over time", h2)]
    for col, trend in notable[:MAX_TREND_CHARTS]:
        series = trend["series"]
        labels = [p["period"] for p in series]
        values = [p["count"] for p in series]
        title = f"Row count by {col} over time ({trend['direction']})"
        story.append(_line_chart(labels, values, title))
        story.append(Spacer(1, 3 * mm))
    return story


def _correlation_bar_section(summary: dict[str, Any], h2, caption) -> list:
    corr = summary.get("correlations") or {}
    pairs = []
    for col_a, targets in corr.items():
        for col_b, r in targets.items():
            if col_a >= col_b or r is None:
                continue
            pairs.append((abs(r), col_a, col_b, r))
    if not pairs:
        return []
    pairs.sort(reverse=True)
    top = pairs[:MAX_CORRELATION_BAR_PAIRS]
    if not top or top[0][0] < MIN_CORRELATION_TO_CHART:
        return []
    labels = [f"{a} vs {b}" for _, a, b, _ in top]
    values = [round(r * 100, 1) for _, _, _, r in top]
    return [
        Paragraph("Strongest correlations", h2),
        Paragraph(
            "r × 100, so +100 is a perfect positive relationship and "
            "−100 is a perfect inverse one.",
            caption,
        ),
        _bar_chart(labels, values, "Correlation strength (r × 100)"),
        Spacer(1, 3 * mm),
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_pdf(filename: str, summary: dict[str, Any], narrative: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"DataScope — {filename}",
        author="DataScope",
    )
    title, meta, h2, body, caption = _styles()
    story = [
        Paragraph(f"DataScope analysis — {filename}", title),
        Paragraph(
            f"Generated {datetime.utcnow().strftime('%B %d, %Y')} · "
            f"{summary['shape']['rows']} rows × {summary['shape']['columns']} columns",
            meta,
        ),
        Paragraph("Narrative", h2),
        Paragraph(narrative.replace("\n", "<br/>"), body),
    ]

    # Charts — distributions, category breakdowns, group comparisons,
    # categorical associations, correlations, and trends. Each section is
    # a no-op if the dataset doesn't have anything notable of that kind.
    story += _distribution_section(summary, h2, caption)
    story += _category_section(summary, h2)
    story += _group_comparison_section(summary, h2, caption)
    story += _association_section(summary, h2, caption)
    story += _correlation_bar_section(summary, h2, caption)
    story += _trend_section(summary, h2)

    # Missing values
    missing = [(k, v) for k, v in summary.get("missing_pct", {}).items() if v > 0]
    if missing:
        story.append(Paragraph("Missing values", h2))
        story.append(
            _kv_table(
                [["Column", "Percent missing"]]
                + [[k, f"{v:.1f}%"] for k, v in missing]
            )
        )
    # Outliers
    outliers = {
        k: v
        for k, v in summary.get("outliers", {}).items()
        if v.get("count")
    }
    if outliers:
        story.append(Paragraph("Outliers (IQR)", h2))
        story.append(
            _kv_table(
                [["Column", "Count", "Share of rows"]]
                + [
                    [k, str(v["count"]), f"{v['share'] * 100:.1f}%"]
                    for k, v in outliers.items()
                ]
            )
        )
    # Strong correlations
    pairs = []
    corr = summary.get("correlations", {})
    for a, targets in corr.items():
        for b, r in targets.items():
            if a >= b or r is None or abs(r) <= 0.7:
                continue
            pairs.append([a, b, f"{r:.3f}"])
    if pairs:
        story.append(Paragraph("Strong correlations", h2))
        story.append(_kv_table([["Column A", "Column B", "r"]] + pairs))
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Generated by DataScope. Upgrade to Pro for unlimited reports.",
            ParagraphStyle(
                "footer",
                parent=meta,
                fontName="Helvetica",
                fontSize=8,
                leading=10,
                textColor=MUTED,
            ),
        )
    )
    doc.build(story)
    return buf.getvalue()
