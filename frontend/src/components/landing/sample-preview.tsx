"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { useChartTheme } from "@/lib/chart-theme";

/**
 * Static mock of the "report card" visual shown in the hero.
 * Mirrors the real report layout: chart + narrated insight, on a
 * secondary surface. Uses accent only for chart highlights.
 */
const missingData = [
  { column: "age", pct: 3 },
  { column: "salary", pct: 8 },
  { column: "email", pct: 34 },
  { column: "churn", pct: 1 },
  { column: "region", pct: 12 },
];

export function SampleReportPreview() {
  const theme = useChartTheme();
  return (
    <div className="card-panel w-full max-w-md p-6 shadow-2xl">
      <div className="flex items-center justify-between">
        <p className="font-heading text-sm font-medium">customers_march.csv</p>
        <span className="rounded-full bg-elevated px-2.5 py-0.5 text-xs text-foreground">
          Ready
        </span>
      </div>

      <div className="mt-5 h-40 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={missingData} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
            <CartesianGrid stroke={theme.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="column" tick={{ fill: theme.ticks, fontSize: 10 }} />
            <YAxis tick={{ fill: theme.ticks, fontSize: 10 }} unit="%" />
            <Bar dataKey="pct" fill={theme.accent} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-5 space-y-3 border-t border-border pt-4 text-sm">
        <p className="text-muted">
          <span className="text-foreground">34% of emails are missing</span> — this
          column should be cleaned before any outreach use.
        </p>
        <p className="text-muted">
          <span className="text-foreground">Salary and age are correlated (r = 0.74)</span>,
          so age explains most of the pay variation in this sample.
        </p>
        <p className="text-muted">
          <span className="text-foreground">Six salary outliers</span> skew the average by 22%.
        </p>
      </div>
    </div>
  );
}
