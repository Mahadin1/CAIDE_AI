"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import type { Summary } from "@/lib/types";

const ACCENT = "#00d4ff";
const MUTED = "#3a4550";
const GRID = "#232a33";

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
            <XAxis dataKey="column" tick={{ fill: "#8A94A3", fontSize: 11 }} />
            <YAxis unit="%" tick={{ fill: "#8A94A3", fontSize: 11 }} />
            <Tooltip
              cursor={{ fill: "rgba(0,212,255,0.06)" }}
              contentStyle={{
                backgroundColor: "#151a21",
                border: "1px solid #232a33",
                borderRadius: 8,
              }}
            />
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
                          backgroundColor: r == null ? "#151a21" : heatColor(r as number),
                          color: r != null && Math.abs(r) > 0.5 ? "#0b0e11" : "#F5F7FA",
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
            <XAxis type="number" dataKey="i" name="index" tick={{ fill: "#8A94A3", fontSize: 10 }} />
            <YAxis
              type="number"
              dataKey="value"
              name="value"
              tick={{ fill: "#8A94A3", fontSize: 10 }}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#151a21",
                border: "1px solid #232a33",
                borderRadius: 8,
              }}
            />
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
}: {
  column: string;
  info: Summary["categorical_summary"][string];
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
          shown as a share of all rows.
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
            <XAxis type="number" unit="%" tick={{ fill: "#8A94A3", fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="value"
              width={96}
              tick={{ fill: "#8A94A3", fontSize: 11 }}
            />
            <Tooltip
              cursor={{ fill: "rgba(0,212,255,0.06)" }}
              contentStyle={{
                backgroundColor: "#151a21",
                border: "1px solid #232a33",
                borderRadius: 8,
              }}
            />
            <Bar dataKey="share" fill={ACCENT} radius={[0, 3, 3, 0]}>
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

export function ReportCharts({ summary }: { summary: Summary }) {
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

  const charts = [];
  if (missingFlagged) charts.push(<MissingValuesChart key="missing" summary={summary} />);
  if (corrFlagged) charts.push(<CorrelationHeatmap key="corr" summary={summary} />);
  if (outlierColumns.length > 0)
    charts.push(
      ...outlierColumns.map((col) => (
        <OutlierScatter key={`outlier-${col}`} column={col} info={summary.outliers[col]} />
      ))
    );
  if (catColumns.length > 0)
    charts.push(
      ...catColumns.map((col) => (
        <CategoricalChart key={`cat-${col}`} column={col} info={summary.categorical_summary[col]} />
      ))
    );

  if (charts.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No issues flagged</CardTitle>
          <CardDescription>
            Nothing crossed the flagging thresholds — no heavy missingness, strong
            correlations, outliers, or dominant categories. Your data is in good shape.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-40 items-center justify-center rounded border border-dashed border-[#232a33]">
            <p className="text-sm text-muted">Charts appear here when something is flagged</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return <div className="grid gap-6 lg:grid-cols-2">{charts}</div>;
}
