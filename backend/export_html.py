"""Self-contained HTML export.

Renders the full report — narrative, sample banner, analysis plan, findings,
key statistics and server-side static charts (matplotlib, Agg backend,
base64-encoded PNG, no external assets) — into a single portable HTML file.

All charts are drawn from `summary_json` only. This module never recomputes a
statistic and never touches the raw file, so an export can never show a
number that disagrees with the live report (the same invariant as pdf.py).
"""
from __future__ import annotations

import base64
import io
import math
import re
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

MAX_CHARTS = 12


# ---------------------------------------------------------------------------
# Chart builders (return base64 PNG data URIs)
# ---------------------------------------------------------------------------

def _style_ax(ax: Any) -> None:
    ax.set_facecolor("#ffffff")
    for spine in ax.spines.values():
        spine.set_color("#d9dde3")
    ax.tick_params(colors="#5a6472", labelsize=8)
    ax.yaxis.grid(True, color="#eceef2", linewidth=0.8)
    ax.set_axisbelow(True)


def _png(ax: Any, height: float = 3.2) -> str:
    fig = ax.figure
    fig.set_size_inches(6.4, height)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _histogram_chart(hist: dict[str, Any], title: str) -> str:
    edges = hist.get("bin_edges") or []
    counts = hist.get("counts") or []
    if len(edges) < 2 or not counts:
        return ""
    fig, ax = plt.subplots()
    labels = [f"{_fmt(edges[i])}–{_fmt(edges[i + 1])}" for i in range(len(counts))]
    ax.bar(labels, counts, color="#00a8cc")
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", rotation=45)
    _style_ax(ax)
    return _png(ax)


def _bar_chart(labels: list[str], values: list[float], title: str) -> str:
    fig, ax = plt.subplots()
    ax.bar([str(l)[:40] for l in labels], values, color="#00a8cc")
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", rotation=45)
    _style_ax(ax)
    return _png(ax)


def _line_chart(labels: list[str], values: list[float], title: str) -> str:
    fig, ax = plt.subplots()
    ax.plot(range(len(values)), values, color="#00a8cc", linewidth=1.6,
            marker="o", markersize=3)
    ax.set_title(title, fontsize=10)
    if len(labels) <= 14:
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels([str(l) for l in labels], rotation=45, fontsize=7)
    else:
        ax.set_xlabel("time")
    _style_ax(ax)
    return _png(ax)


def _corr_heatmap(summary: dict[str, Any]) -> str:
    corr = summary.get("correlations") or {}
    cols = list(corr.keys())
    if len(cols) < 2:
        return ""
    matrix = [[corr[a].get(b, 0) if corr.get(a) else 0 for b in cols]
              for a in cols]
    fig, ax = plt.subplots()
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels([c[:18] for c in cols], rotation=90, fontsize=7)
    ax.set_yticklabels([c[:18] for c in cols], fontsize=7)
    fig.colorbar(im, shrink=0.8, label="Pearson r")
    ax.set_title("Correlation heatmap", fontsize=10)
    fig.tight_layout()
    return _png(ax)


def _render_charts(summary: dict[str, Any]) -> list[str]:
    charts: list[str] = []
    classification = summary.get("column_classification", {})

    for col, hist in (summary.get("histograms") or {}).items():
        charts.append(_histogram_chart(hist, f"Distribution of {col}"))
        if len(charts) >= MAX_CHARTS:
            return charts

    for col, info in (summary.get("categorical_summary") or {}).items():
        if classification.get(col, {}).get("kind") in (
            "date_like", "mixed", "identifier", "constant", "empty", "free_text"
        ):
            continue
        if info.get("top"):
            charts.append(_bar_chart(
                [t["value"] for t in info["top"]],
                [t["count"] for t in info["top"]],
                f"Top values of {col}",
            ))
            if len(charts) >= MAX_CHARTS:
                return charts

    for cmp in (summary.get("numeric_by_categorical") or {}).values():
        charts.append(_bar_chart(
            [g["group"] for g in cmp["groups"]],
            [g["mean"] for g in cmp["groups"]],
            f"Average {cmp['numeric_column']} by {cmp['category_column']}",
        ))
        if len(charts) >= MAX_CHARTS:
            return charts

    for col, trend in (summary.get("time_trends") or {}).items():
        if trend.get("series"):
            charts.append(_line_chart(
                [p["period"] for p in trend["series"]],
                [p["count"] for p in trend["series"]],
                f"Row count by {col} over time",
            ))
            if len(charts) >= MAX_CHARTS:
                return charts

    heat = _corr_heatmap(summary)
    if heat:
        charts.append(heat)
    return charts


def _fmt(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v is None or math.isnan(v):
        return "–"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.4g}"


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def _escape(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_html(
    filename: str,
    summary: dict[str, Any],
    narrative: str,
    *,
    plan_tasks: list[dict[str, Any]] | None = None,
    sample_info: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    source_format: str | None = None,
) -> str:
    """Build the complete self-contained HTML document."""
    shape = summary.get("shape", {})
    charts = _render_charts(summary)
    plan_tasks = plan_tasks or summary.get("executed_tasks") or []
    findings = findings or []

    severity_color = {"high": "#b91c1c", "medium": "#b45309", "low": "#2563eb"}

    sample_html = ""
    if sample_info and sample_info.get("mode") != "full":
        sample_html = f"""
        <div style="background:#fdf3e7;border:1px solid #f0c48f;border-radius:8px;padding:12px 16px;margin:16px 0;">
          <strong>Sample-based analysis</strong><br/>
          <span style="color:#6b7280;">
            The file has {_fmt(sample_info.get('total_rows'))} rows; detailed
            analyses used a deterministic random sample of
            {_fmt(sample_info.get('sample_rows'))} rows.
            Proportions carry a worst-case margin of error of
            ±{sample_info.get('margin_of_error', 0) * 100:.1f} percentage
            points at 95% confidence. Exact global aggregates were computed
            over every row.
          </span>
        </div>"""

    plan_html = ""
    if plan_tasks:
        items = "".join(
            f"<li><strong>{_escape(t.get('type'))}</strong> — "
            f"{_escape(t.get('description'))} "
            f"<span style='color:#6b7280'>({_escape(t.get('rationale'))})</span></li>"
            for t in plan_tasks[:12]
        )
        plan_html = f"""
        <div style="margin:24px 0;">
          <h2 style="font-size:18px;margin-bottom:8px;">Analysis plan</h2>
          <ul style="color:#374151;line-height:1.7;padding-left:20px;">{items}</ul>
        </div>"""

    findings_html = ""
    if findings:
        cards = []
        for f in findings[:40]:
            color = severity_color.get(f.get("severity", "low"), "#2563eb")
            cards.append(f"""
            <div style="border:1px solid #e5e7eb;border-left:4px solid {color};
                        border-radius:6px;padding:12px 16px;margin:10px 0;">
              <div style="font-size:13px;color:#6b7280;text-transform:uppercase;">
                {_escape(f.get('type'))} · {_escape(f.get('severity'))}</div>
              <div style="margin-top:4px;"><strong>{_escape(f.get('message'))}</strong></div>
              <div style="margin-top:6px;color:#374151;">{_escape(f.get('interpretation', ''))}</div>
              <div style="margin-top:6px;font-size:13px;color:#6b7280;">
                <em>Next step:</em> {_escape(f.get('action', ''))}</div>
              <div style="margin-top:6px;font-size:12px;color:#9ca3af;">
                Method: {_escape(f.get('method', ''))}</div>
            </div>""")
        findings_html = f"""
        <div style="margin:24px 0;">
          <h2 style="font-size:18px;margin-bottom:8px;">Findings</h2>
          {''.join(cards)}
        </div>"""

    charts_html = "".join(
        f'<img src="{c}" style="max-width:100%;margin:10px 0;border-radius:6px;" alt="chart"/>'
        for c in charts
    )

    missing_html = ""
    missing = [(k, v) for k, v in summary.get("missing_pct", {}).items() if v > 0]
    if missing:
        rows = "".join(
            f"<tr><td>{_escape(k)}</td><td>{v:.1f}%</td></tr>" for k, v in missing[:20]
        )
        missing_html = f"""
        <h2 style="font-size:18px;margin:24px 0 8px;">Missing values</h2>
        <table style="border-collapse:collapse;font-size:13px;">
          <tr><th style="text-align:left;padding:4px 12px;border-bottom:1px solid #d9dde3;">Column</th>
          <th style="text-align:left;padding:4px 12px;border-bottom:1px solid #d9dde3;">Percent missing</th></tr>
          {rows}
        </table>"""

    paragraphs = "".join(
        f"<p style='margin:10px 0;line-height:1.8;color:#374151;'>{_escape(p)}</p>"
        for p in str(narrative).split("\n") if p.strip()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DataScope — {_escape(filename)}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         margin:0; background:#f7f8fa; color:#0b0e11; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .meta {{ color:#6b7280; font-size: 13px; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px;
          padding:20px 24px; margin:16px 0; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>DataScope analysis — {_escape(filename)}</h1>
    <div class="meta">
      Generated {datetime.utcnow().strftime('%B %d, %Y')} ·
      {_fmt(shape.get('rows'))} rows × {_fmt(shape.get('columns'))} columns ·
      format {_escape(source_format or 'unknown')}
    </div>
    {sample_html}
  </div>

  <div class="card">
    <h2 style="font-size:18px;margin:0 0 8px;">Narrative</h2>
    {paragraphs}
  </div>

  {plan_html}
  {findings_html}

  <div class="card">
    <h2 style="font-size:18px;margin:0 0 8px;">Charts</h2>
    {charts_html}
  </div>

  <div class="card">{missing_html}</div>

  <div class="meta" style="text-align:center;margin-top:24px;">
    Generated by DataScope. Numbers are computed by deterministic
    statistics; the narrative was produced by an AI assistant from those
    statistics only.
  </div>
</div>
</body>
</html>"""
