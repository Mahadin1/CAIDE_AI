"use client";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RowDrilldown } from "@/components/report/row-drilldown";
import type {
  AnomalyResult,
  CohortResult,
  FeatureEngineeringResult,
  ForecastResult,
  ForecastResultEntry,
  GroupSignificanceResult,
  SegmentationResult,
  Summary,
} from "@/lib/types";

const ACCENT = "#fafafa";
const MUTED = "#3a3a3a";
const GRID = "#1f1f1f";
const TOOLTIP_STYLE = {
  backgroundColor: "#0a0a0a",
  border: "1px solid #1f1f1f",
  borderRadius: 8,
};

function fmt(x: number | undefined | null, nd = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toFixed(nd);
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function SegmentationSection({
  res,
  reportId,
}: {
  res: SegmentationResult;
  reportId: string;
}) {
  const [drill, setDrill] = useState<{ cluster: string; title: string } | null>(null);
  const clusters = res.clusters ?? [];
  if (clusters.length === 0) return null;
  const chart = clusters.map((c) => ({
    name: `Segment ${c.cluster}`,
    size: c.size,
    share: Math.round(c.share * 1000) / 10,
  }));
  const cols = Object.keys(clusters[0]?.centroid ?? {});
  return (
    <>
      <SectionCard
        title="Automatic segmentation"
        description={`${res.k} segments found (silhouette ${fmt(res.silhouette, 3)}). Rows are grouped by their numeric profile — click a segment to inspect its rows.`}
      >
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#888888", fontSize: 11 }} />
              <YAxis tick={{ fill: "#888888", fontSize: 11 }} allowDecimals={false} />
              <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
              <Bar
                dataKey="size"
                fill={ACCENT}
                radius={[3, 3, 0, 0]}
                className="cursor-pointer"
                onClick={(b) =>
                  setDrill({ cluster: String((b as { name: string }).name).replace("Segment ", ""), title: "Rows in segment" })
                }
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                <th className="border-b border-border px-3 py-2 text-xs text-muted">Segment</th>
                <th className="border-b border-border px-3 py-2 text-xs text-muted">Rows</th>
                <th className="border-b border-border px-3 py-2 text-xs text-muted">Share</th>
                {cols.map((c) => (
                  <th key={c} className="border-b border-border px-3 py-2 text-xs text-muted">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {clusters.map((c) => (
                <tr key={c.cluster} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2">
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                      onClick={() =>
                        setDrill({ cluster: String(c.cluster), title: "Rows in segment" })
                      }
                    >
                      Segment {c.cluster}
                    </Button>
                  </td>
                  <td className="px-3 py-2">{c.size.toLocaleString()}</td>
                  <td className="px-3 py-2">{Math.round(c.share * 1000) / 10}%</td>
                  {cols.map((col) => (
                    <td key={col} className="px-3 py-2">
                      {fmt(c.centroid[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
      {drill && (
        <IndicesDrilldown
          reportId={reportId}
          indices={res.row_positions?.[drill.cluster] ?? []}
          title={`${drill.title} ${drill.cluster}`}
          onClose={() => setDrill(null)}
        />
      )}
    </>
  );
}

function ForecastSection({
  res,
}: {
  res: ForecastResult;
}) {
  const rawEntries = Object.entries(res);
  const entries = rawEntries.filter(
    ([k, v]) => k !== "_capped" && typeof v === "object" && v !== null && "history" in v
  ) as [string, ForecastResultEntry][];
  if (entries.length === 0) return null;
  return (
    <SectionCard
      title="Metric forecast"
      description="Forecast for the next 6 periods with a 95% confidence band. The band width is the honest measure of how certain the outlook is."
    >
      <div className="space-y-6">
        {entries.map(([key, e]) => {
          const labels = [...e.periods, ...Array.from({ length: e.horizon }, (_, i) => `+${i + 1}`)];
          const data = labels.map((label, i) => {
            const isForecast = i >= e.periods.length;
            return {
              label,
              history: !isForecast ? e.history[i] : null,
              mean: isForecast ? e.mean[i - e.periods.length] : null,
              upper: isForecast ? e.upper[i - e.periods.length] : null,
              lower: isForecast ? e.lower[i - e.periods.length] : null,
            };
          });
          return (
            <div key={key}>
              <p className="text-sm font-medium">
                {e.metric_column} by {e.date_column}
              </p>
              <p className="mb-2 text-xs text-muted">
                {e.model} · trained on {e.periods_trained} periods
                {e.trend_detectable ? " · trend detectable" : " · no clear trend"}
              </p>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                    <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fill: "#888888", fontSize: 10 }} />
                    <YAxis tick={{ fill: "#888888", fontSize: 11 }} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Line type="monotone" dataKey="history" stroke={MUTED} strokeWidth={1.5} dot={false} name="History" />
                    <Line type="monotone" dataKey="mean" stroke={ACCENT} strokeWidth={2} dot={false} name="Forecast" />
                    <Line type="monotone" dataKey="upper" stroke={ACCENT} strokeOpacity={0.3} strokeDasharray="3 3" dot={false} name="Upper" />
                    <Line type="monotone" dataKey="lower" stroke={ACCENT} strokeOpacity={0.3} strokeDasharray="3 3" dot={false} name="Lower" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          );
        })}
        {res._capped && (
          <p className="text-xs text-muted">
            More date + metric pairs were candidates; only the strongest was forecast (configurable).
          </p>
        )}
      </div>
    </SectionCard>
  );
}

function CohortSection({ res }: { res: CohortResult }) {
  const notable = res.most_notable;
  return (
    <SectionCard
      title="Cohort retention"
      description={`Retention by cohort (first-appearance month) over periods since first appearance, for ${res.identifier_column} + ${res.date_column}.`}
    >
      {notable && (
        <div className="mb-4 rounded-md border border-[#3a3320] bg-[#1a160c] p-3">
          <p className="text-sm">
            Most notable: the <strong>{notable.cohort}</strong> cohort drops{" "}
            {fmt(notable.drop, 1)}pp retention from period {notable.period - 1} to{" "}
            {notable.period} ({fmt(notable.retention_before, 1)}% →{" "}
            {fmt(notable.retention_after, 1)}%).
          </p>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr>
              <th className="border-b border-border px-3 py-2 text-xs text-muted">Cohort</th>
              <th className="border-b border-border px-3 py-2 text-xs text-muted">Size</th>
              {res.periods.map((p) => (
                <th key={p} className="border-b border-border px-3 py-2 text-right text-xs text-muted">
                  P{p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {res.matrix.map((m) => (
              <tr key={m.cohort} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-2 font-medium">{m.cohort}</td>
                <td className="px-3 py-2">{m.cohort_size.toLocaleString()}</td>
                {m.retention.map((r, i) => (
                  <td
                    key={i}
                    className={`px-3 py-2 text-right ${r >= 60 ? "text-foreground" : r >= 30 ? "text-muted" : "text-[#f87171]"}`}
                  >
                    {r.toFixed(0)}%
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function GroupSignificanceSection({ res }: { res: GroupSignificanceResult }) {
  const entries = Object.values(res).filter((e) => e && e.significant);
  if (entries.length === 0) return null;
  return (
    <SectionCard
      title="Group significance tests"
      description="Formal two-group comparisons (t-test / Mann-Whitney U) with effect size. A 'statistically significant difference' is an association, not a causal claim."
    >
      <div className="space-y-2">
        {entries.map((e) => (
          <div key={`${e.numeric_column}__by__${e.category_column}`} className="rounded-md border border-border bg-elevated p-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium">
                {e.numeric_column}: {e.group_a} vs {e.group_b}
              </p>
              <Badge variant="secondary">p={e.p_value.toPrecision(3)}</Badge>
              <Badge variant="secondary">d={fmt(e.effect_size_d)}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Mean {fmt(e.mean_a)} vs {fmt(e.mean_b)} · n={e.n_a}/{e.n_b} · {e.method}
            </p>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function FeatureEngineeringSection({ res }: { res: FeatureEngineeringResult }) {
  const logs = res.log_transform_candidates ?? [];
  const enc = res.encoding_suggestions ?? [];
  const red = res.redundant_pairs ?? [];
  if (!logs.length && !enc.length && !red.length) return null;
  return (
    <SectionCard
      title="Feature engineering suggestions"
      description="Rule-based advice only — nothing was changed. Apply these in your own pipeline before modelling."
    >
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {logs.map((l) => (
          <li key={l.column}>
            Log-transform <strong>{l.column}</strong> (skew {fmt(l.skew, 2)}) — {l.suggestion}.
          </li>
        ))}
        {enc.map((e) => (
          <li key={e.column}>
            <strong>{e.column}</strong>: {e.suggestion}.
          </li>
        ))}
        {red.map((p) => (
          <li key={`${p.column_a}~${p.column_b}`}>
            <strong>{p.column_a}</strong> and <strong>{p.column_b}</strong> are near-duplicates
            (r = {fmt(p.correlation, 2)}) — keep one.
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function AnomalySection({
  res,
  reportId,
}: {
  res: AnomalyResult;
  reportId: string;
}) {
  const [drill, setDrill] = useState(false);
  const top = res.chart_data ?? [];
  const chart = top.slice(0, 15).map((d, i) => ({ i, score: d.score }));
  return (
    <>
      <SectionCard
        title="Multivariate anomaly detection"
        description={`${res.n_flagged} rows (${Math.round((res.share_flagged ?? 0) * 1000) / 10}%) are unusual in COMBINATION across the numeric columns — a per-column IQR check would miss them.`}
      >
        {chart.length > 0 && (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="i" tick={{ fill: "#888888", fontSize: 10 }} />
                <YAxis tick={{ fill: "#888888", fontSize: 11 }} />
                <Tooltip cursor={{ fill: "rgba(250,250,250,0.06)" }} contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="score" fill={ACCENT} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <Button size="sm" variant="outline" className="mt-3" onClick={() => setDrill(true)}>
          Inspect flagged rows
        </Button>
      </SectionCard>
      {drill && (
        <IndicesDrilldown
          reportId={reportId}
          indices={res.row_positions ?? []}
          title="Flagged multivariate outliers"
          onClose={() => setDrill(false)}
        />
      )}
    </>
  );
}

function IndicesDrilldown({
  reportId,
  indices,
  title,
  onClose,
}: {
  reportId: string;
  indices: number[];
  title: string;
  onClose: () => void;
}) {
  if (indices.length === 0) return null;
  return (
    <RowDrilldown
      reportId={reportId}
      column=""
      value={indices.join(",")}
      title={title}
      onClose={onClose}
      useIndices
    />
  );
}

export function AdaptiveResults({
  summary,
  reportId,
}: {
  summary: Summary;
  reportId?: string;
}) {
  const adaptive = summary.adaptive;
  if (!adaptive || Object.keys(adaptive).length === 0) return null;
  const seg = adaptive.auto_segmentation as SegmentationResult | undefined;
  const forecast = adaptive.forecast_metric as ForecastResult | undefined;
  const cohort = adaptive.cohort_retention as CohortResult | undefined;
  const gst = adaptive.group_significance_test as GroupSignificanceResult | undefined;
  const fe = adaptive.feature_engineering_suggestions as FeatureEngineeringResult | undefined;
  const anomaly = adaptive.multivariate_anomaly_detection as AnomalyResult | undefined;

  const sections: React.ReactNode[] = [];
  if (seg && !seg.skipped && seg.clusters?.length) sections.push(<SegmentationSection key="seg" res={seg} reportId={reportId ?? ""} />);
  if (forecast) sections.push(<ForecastSection key="fc" res={forecast} />);
  if (cohort && !cohort.skipped && cohort.matrix?.length) sections.push(<CohortSection key="cohort" res={cohort} />);
  if (gst) sections.push(<GroupSignificanceSection key="gst" res={gst} />);
  if (fe && !fe.skipped && fe.advisory) sections.push(<FeatureEngineeringSection key="fe" res={fe} />);
  if (anomaly && !anomaly.skipped && (anomaly.n_flagged ?? 0) > 0) sections.push(<AnomalySection key="anom" res={anomaly} reportId={reportId ?? ""} />);

  if (sections.length === 0) return null;
  return (
    <div>
      <h2 className="mb-2 text-lg font-medium">Deep-dive analyses</h2>
      <div className="space-y-6">{sections}</div>
    </div>
  );
}
