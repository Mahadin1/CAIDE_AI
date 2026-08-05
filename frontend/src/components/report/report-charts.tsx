"use client";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
  Tooltip,
  ZAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RowDrilldown } from "@/components/report/row-drilldown";
import type {
  CategoricalAssociationEntry,
  GroupComparisonEntry,
  HistogramInfo,
  Summary,
  TimeTrendEntry,
} from "@/lib/types";
const ACCENT = "#fafafa";
const MUTED = "#3a3a3a";
const GRID = "#1f1f1f";

// Mirrors the thresholds of the same name in agent.py's select_findings /
// pdf.py, so a chart only appears here when the narrative also considers
// it worth mentioning.
const SKEW_THRESHOLD = 1.0;
const GROUP_DIFFERENCE_MIN_EFFECT = 0.5;
const CRAMERS_V_ASSOCIATION_THRESHOLD = 0.3;
const TREND_CORR_THRESHOLD = 0.5;

const TOOLTIP_STYLE = {
  backgroundColor: "#0a0a0a",
  border: "1px solid #1f1f1f",
  borderRadius: 8,
};

function fmtNum(x: number): string {
  const ax = Math.abs(x);
  if (ax >= 1000) return Math.round(x).toLocaleString();
  if (ax >= 1) return x.toFixed(1);
  return x.toPrecision(3);
}

function heatColor(r: number): string {
  const a = Math.min(1, Math.abs(r));
  // accent with alpha — only used for chart highlights
  const hex = Math.round(a * 255)
    .toString(16)
    .padStart(2, "0");
  return `${ACCENT}${hex}`;
}
/* ------------------------------------------------------------------ */
/* Missing values bar chart                                            */
/* ------------------------------------------------------------------ */
function MissingValuesChart({ summary }: { summary: Summary }) {
  const data = Object.entries(summary.missing_pct)
    .map(([column, pct]) => ({ column, pct: Math.round(pct * 10) / 10 }))
    .filter((d) => d.pct > 0)
    .sort((a, b) => b.pct - a.pct);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Missing values</CardTitle>
        <CardDescription>
          Columns flagged above 20% are highlighted — these need attention first.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="column" tick={{ fill: "#888888", fontSize: 11 }} />
            <YAxis unit="%" tick={{ fill: "#888888", fontSize: 11 }} />
            <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="pct" radius={[3, 3, 0, 0]}>
              {data.map((d) => (
                <Cell key={d.column} fill={d.pct > 20 ? ACCENT : MUTED} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Correlation heatmap (grid, |r| -> accent intensity)                 */
/* ------------------------------------------------------------------ */
function CorrelationHeatmap({ summary }: { summary: Summary }) {
  const corr = summary.correlations;
  const cols = Object.keys(corr);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Correlation heatmap</CardTitle>
        <CardDescription>
          Strong relationships (|r| &gt; 0.7) glow brightest.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="inline-block">
            <div
              className="grid gap-1"
              style={{
                gridTemplateColumns: `repeat(${cols.length + 1}, minmax(0,1fr))`,
              }}
            >
              <div />
              {cols.map((c) => (
                <div key={c} className="px-1 text-center text-xs text-muted">
                  {c}
                </div>
              ))}
              {cols.map((a) => (
                <div key={a} className="contents">
                  <div className="flex items-center px-1 text-xs text-muted">{a}</div>
                  {cols.map((b) => {
                    const r = corr[a]?.[b];
                    return (
                      <div
                        key={b}
                        title={`${a} vs ${b}: ${r ?? "n/a"}`}
                        className="flex h-10 items-center justify-center rounded text-xs"
                        style={{
                          backgroundColor: r == null ? "#0a0a0a" : heatColor(r as number),
                          color: r != null && Math.abs(r) > 0.5 ? "#000000" : "#FAFAFA",
                        }}
                      >
                        {r != null ? Math.round(r * 100) / 100 : "—"}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}


/* ------------------------------------------------------------------ */
/* Outlier scatter — sample outlier values vs the IQR band             */
/* ------------------------------------------------------------------ */
function OutlierScatter({
  column,
  info,
}: {
  column: string;
  info: Summary["outliers"][string];
}) {
  const sample = info.outlier_sample ?? [];
  const points = sample.map((v, i) => ({ i, value: v }));
  const low = info.low_bound;
  const high = info.high_bound;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Outliers in “{column}”</CardTitle>
        <CardDescription>
          {info.count} outlier{info.count === 1 ? "" : "s"} ({Math.round(info.share * 1000) / 10}% of
          rows). Points outside the IQR band are highlighted.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis type="number" dataKey="i" name="index" tick={{ fill: "#888888", fontSize: 10 }} />
            <YAxis
              type="number"
              dataKey="value"
              name="value"
              tick={{ fill: "#888888", fontSize: 10 }}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            {low != null && high != null && (
              <ReferenceArea
                y1={low}
                y2={high}
                fill={ACCENT}
                fillOpacity={0.08}
                stroke={ACCENT}
                strokeOpacity={0.2}
              />
            )}
            <Scatter data={points}>
              {points.map((p, idx) => (
                <Cell
                  key={idx}
                  fill={
                    low != null && high != null && (p.value < low || p.value > high)
                      ? ACCENT
                      : MUTED
                  }
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
/* ------------------------------------------------------------------ */
/* Categorical distribution bar chart                                  */
/* ------------------------------------------------------------------ */
function CategoricalChart({
  column,
  info,
  onDrill,
}: {
  column: string;
  info: Summary["categorical_summary"][string];
  onDrill: (column: string, value: string, title: string) => void;
}) {
  const data = info.top.map((t) => ({
    value: t.value,
    share: Math.round(t.share * 1000) / 10,
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribution of “{column}”</CardTitle>
        <CardDescription>
          {info.cardinality} distinct value{info.cardinality === 1 ? "" : "s"} — the top ones are
          shown as a share of all rows. Click a bar to inspect the rows behind it.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
          >
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" unit="%" tick={{ fill: "#888888", fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="value"
              width={96}
              tick={{ fill: "#888888", fontSize: 11 }}
            />
            <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
            <Bar
              dataKey="share"
              fill={ACCENT}
              radius={[0, 3, 3, 0]}
              className="cursor-pointer"
              onClick={(entry) => onDrill(column, String((entry as { value: unknown }).value), `Distribution of “${column}”`)}
            >
              {data.map((d) => (
                <Cell key={d.value} fill={d.share > 90 ? ACCENT : MUTED} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Histogram — distribution of a (usually skewed) numeric column       */
/* ------------------------------------------------------------------ */
function HistogramChart({
  column,
  hist,
  skew,
}: {
  column: string;
  hist: HistogramInfo;
  skew: number | null;
}) {
  const data = hist.counts.map((count, i) => ({
    range: `${fmtNum(hist.bin_edges[i])}–${fmtNum(hist.bin_edges[i + 1])}`,
    count,
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribution of “{column}”</CardTitle>
        <CardDescription>
          {skew != null
            ? `Skew = ${skew.toFixed(2)} — the mean can be misleading here; the median is a safer summary.`
            : "Bar height shows how many rows fall into each value range."}
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 24 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="range"
              tick={{ fill: "#888888", fontSize: 9 }}
              angle={-30}
              textAnchor="end"
              height={40}
            />
            <YAxis tick={{ fill: "#888888", fontSize: 11 }} allowDecimals={false} />
            <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="count" fill={ACCENT} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Group comparison — mean of a numeric column, broken down by category */
/* ------------------------------------------------------------------ */
function GroupComparisonChart({
  entry,
  onDrill,
}: {
  entry: GroupComparisonEntry;
  onDrill: (column: string, value: string, title: string) => void;
}) {
  const data = entry.groups.map((g) => ({ group: g.group, mean: g.mean }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Average “{entry.numeric_column}” by “{entry.category_column}”
        </CardTitle>
        <CardDescription>
          A bigger gap between bars means a stronger relationship between the
          two columns. Click a bar to inspect the rows in that group.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="group" tick={{ fill: "#888888", fontSize: 11 }} />
            <YAxis tick={{ fill: "#888888", fontSize: 11 }} />
            <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
            <Bar
              dataKey="mean"
              fill={ACCENT}
              radius={[3, 3, 0, 0]}
              className="cursor-pointer"
              onClick={(bar) =>
                onDrill(
                  entry.category_column,
                  String((bar as { group: unknown }).group),
                  `Average “${entry.numeric_column}” by “${entry.category_column}”`
                )
              }
            />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Categorical associations — Cramér's V per notable pair              */
/* ------------------------------------------------------------------ */
function CategoricalAssociationChart({ entries }: { entries: CategoricalAssociationEntry[] }) {
  const data = entries.map((e) => ({
    pair: `${e.column_a} × ${e.column_b}`,
    v: Math.round(e.cramers_v * 100),
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Categorical associations</CardTitle>
        <CardDescription>
          Cramér&apos;s V: how strongly two categorical columns move together, from 0
          (unrelated) to 100 (perfectly related).
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
          >
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" domain={[0, 100]} tick={{ fill: "#888888", fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="pair"
              width={140}
              tick={{ fill: "#888888", fontSize: 11 }}
            />
            <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="v" fill={ACCENT} radius={[0, 3, 3, 0]}>
              {data.map((d) => (
                <Cell key={d.pair} fill={d.v >= 70 ? ACCENT : MUTED} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Time trend — row count per period for a date-like column            */
/* ------------------------------------------------------------------ */
function TimeTrendChart({ column, trend }: { column: string; trend: TimeTrendEntry }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>“{column}” over time</CardTitle>
        <CardDescription>
          Row count is {trend.direction} from {trend.start} to {trend.end}.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={trend.series} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="period" tick={{ fill: "#888888", fontSize: 10 }} />
            <YAxis tick={{ fill: "#888888", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Line
              type="monotone"
              dataKey="count"
              stroke={ACCENT}
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Auto-selection wrapper — only charts relevant to flagged findings   */
/* ------------------------------------------------------------------ */
// Columns the classifier re-labelled as non-categorical should never be
// charted as a normal category (they are covered by their own findings).
const NON_CATEGORICAL_KINDS = new Set([
  "date_like",
  "mixed",
  "identifier",
  "constant",
  "empty",
]);
export function ReportCharts({ summary, reportId }: { summary: Summary; reportId?: string }) {
  const [drill, setDrill] = useState<{
    column: string;
    value: string;
    title: string;
  } | null>(null);
  const classification = summary.column_classification ?? {};
  const missingFlagged = Object.values(summary.missing_pct).some((p) => p > 20);
  const corrFlagged = Object.entries(summary.correlations).some(([a, targets]) =>
    Object.entries(targets).some(
      ([b, r]) => a > b && r != null && Math.abs(r as number) > 0.7
    )
  );
  const outlierColumns = Object.entries(summary.outliers)
    .filter(([, info]) => info.count > 0 && info.share > 0.01)
    .sort((a, b) => b[1].share - a[1].share)
    .slice(0, 3)
    .map(([col]) => col);
  const catColumns = Object.entries(summary.categorical_summary)
    .filter(([col, info]) => {
      const kind = classification[col]?.kind;
      if (kind && NON_CATEGORICAL_KINDS.has(kind)) return false;
      return info.cardinality > 1 && info.top[0]?.share > 0.9;
    })
    .map(([col]) => col);

  // Heavily skewed numeric columns — same threshold agent.py uses to flag
  // the "median is safer than the mean" finding.
  const skewedColumns = Object.entries(summary.numeric_stats)
    .map(([col, stats]) => [col, stats.skew] as const)
    .filter((entry): entry is [string, number] => entry[1] != null && Math.abs(entry[1]) > SKEW_THRESHOLD)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3);

  // Notable numeric-by-category comparisons, strongest effect size first.
  const groupComparisons = Object.values(summary.numeric_by_categorical ?? {})
    .filter((c) => Math.abs(c.effect_size_std) >= GROUP_DIFFERENCE_MIN_EFFECT)
    .sort((a, b) => Math.abs(b.effect_size_std) - Math.abs(a.effect_size_std))
    .slice(0, 3);

  // Notable categorical-vs-categorical associations, rendered as one chart.
  const associations = Object.values(summary.categorical_associations ?? {})
    .filter((a) => a.cramers_v >= CRAMERS_V_ASSOCIATION_THRESHOLD)
    .sort((a, b) => b.cramers_v - a.cramers_v)
    .slice(0, 5);

  // Notable time trends, strongest correlation first.
  const trends = Object.entries(summary.time_trends ?? {})
    .filter(([, t]) => Math.abs(t.trend_correlation) >= TREND_CORR_THRESHOLD && t.series?.length)
    .sort((a, b) => Math.abs(b[1].trend_correlation) - Math.abs(a[1].trend_correlation))
    .slice(0, 3);

  const charts = [];
  if (missingFlagged) charts.push(<MissingValuesChart key="missing" summary={summary} />);
  if (corrFlagged) charts.push(<CorrelationHeatmap key="corr" summary={summary} />);
  if (outlierColumns.length > 0)
    charts.push(
      ...outlierColumns.map((col) => (
        <OutlierScatter key={`outlier-${col}`} column={col} info={summary.outliers[col]} />
      ))
    );
  if (skewedColumns.length > 0) {
    const histograms = summary.histograms ?? {};
    charts.push(
      ...skewedColumns
        .filter(([col]) => histograms[col])
        .map(([col, skew]) => (
          <HistogramChart key={`hist-${col}`} column={col} hist={histograms[col]} skew={skew} />
        ))
    );
  }
  if (catColumns.length > 0)
    charts.push(
      ...catColumns.map((col) => (
        <CategoricalChart
          key={`cat-${col}`}
          column={col}
          info={summary.categorical_summary[col]}
          onDrill={(c, v, t) => setDrill({ column: c, value: v, title: t })}
        />
      ))
    );
  if (groupComparisons.length > 0)
    charts.push(
      ...groupComparisons.map((entry) => (
        <GroupComparisonChart
          key={`group-${entry.numeric_column}-${entry.category_column}`}
          entry={entry}
          onDrill={(c, v, t) => setDrill({ column: c, value: v, title: t })}
        />
      ))
    );
  if (associations.length > 0)
    charts.push(<CategoricalAssociationChart key="associations" entries={associations} />);
  if (trends.length > 0)
    charts.push(
      ...trends.map(([col, trend]) => (
        <TimeTrendChart key={`trend-${col}`} column={col} trend={trend} />
      ))
    );

  if (charts.length === 0) {
    return (
      <>
        <Card>
          <CardHeader>
            <CardTitle>No issues flagged</CardTitle>
            <CardDescription>
              Nothing crossed the flagging thresholds — no heavy missingness, strong
              correlations, outliers, skew, notable group differences, category
              associations, dominant categories, or time trends. Your data is in good
              shape.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex h-40 items-center justify-center rounded border border-dashed border-[#1f1f1f]">
              <p className="text-sm text-muted">Charts appear here when something is flagged</p>
            </div>
          </CardContent>
        </Card>
        {drill && reportId && (
          <RowDrilldown
            reportId={reportId}
            column={drill.column}
            value={drill.value}
            title={drill.title}
            onClose={() => setDrill(null)}
          />
        )}
      </>
    );
  }
  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">{charts}</div>
      {drill && reportId && (
        <RowDrilldown
          reportId={reportId}
          column={drill.column}
          value={drill.value}
          title={drill.title}
          onClose={() => setDrill(null)}
        />
      )}
    </>
  );
}
