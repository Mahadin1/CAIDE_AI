import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Summary } from "@/lib/types";

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

/**
 * A short, plain-English "at a glance" summary rendered at the top of the
 * report. Everything here is computed deterministically from the stored
 * summary_json, so it can never contradict the narrative or the charts.
 */
export function ReportOverview({ summary }: { summary: Summary }) {
  const classification = summary.column_classification ?? {};

  const kinds = new Map<string, number>();
  const kindLabel = new Map<string, string>([
    ["numeric", "numeric"],
    ["categorical", "categorical"],
    ["date_like", "date"],
    ["boolean", "boolean"],
    ["free_text", "free-text"],
    ["identifier", "identifier"],
    ["mixed", "mixed"],
    ["constant", "constant"],
    ["empty", "empty"],
  ]);
  for (const col of Object.keys(summary.dtypes ?? {})) {
    const kind = classification[col]?.kind ?? "categorical";
    kinds.set(kind, (kinds.get(kind) ?? 0) + 1);
  }
  const mix = [...kinds.entries()]
    .map(([kind, count]) => ({ kind, count, label: kindLabel.get(kind) ?? kind }))
    .sort((a, b) => b.count - a.count);

  const missingCols = Object.entries(summary.missing_pct ?? {}).filter(
    ([, p]) => p > 0
  );
  const maxMissing = missingCols.sort((a, b) => b[1] - a[1])[0];

  const duplicateShare = summary.duplicate_share ?? 0;

  const nonCategorical = new Set([
    "date_like",
    "mixed",
    "identifier",
    "constant",
    "empty",
  ]);
  const dominantCategories = Object.entries(summary.categorical_summary ?? {})
    .filter(([col, info]) => {
      const kind = classification[col]?.kind;
      if (kind && nonCategorical.has(kind)) return false;
      return info.cardinality > 1 && info.top?.[0];
    })
    .map(([col, info]) => ({
      col,
      top: info.top[0].value,
      share: info.top[0].share,
    }))
    .sort((a, b) => b.share - a.share)
    .slice(0, 3);

  const corrPairs: { a: string; b: string; r: number }[] = [];
  const corr = summary.correlations ?? {};
  for (const [a, targets] of Object.entries(corr)) {
    for (const [b, r] of Object.entries(targets)) {
      if (a >= b || r == null) continue;
      corrPairs.push({ a, b, r: r as number });
    }
  }
  corrPairs.sort((x, y) => Math.abs(y.r) - Math.abs(x.r));
  const strongCorr = corrPairs
    .filter((c) => Math.abs(c.r) >= 0.5)
    .slice(0, 2);

  const statements: string[] = [];

  if (maxMissing) {
    statements.push(
      `The most incomplete column is “${maxMissing[0]}” with ${maxMissing[1].toFixed(1)}% of its values missing.`
    );
  } else {
    statements.push("There is no missing data to worry about.");
  }
  if (duplicateShare > 0) {
    statements.push(
      `${pct(duplicateShare)} of rows are exact duplicates.`
    );
  } else {
    statements.push("No duplicate rows were found.");
  }
  if (dominantCategories.length > 0) {
    const parts = dominantCategories
      .map(
        (d) =>
          `“${d.col}” is mostly “${d.top}” (${pct(d.share)})`
      )
      .join(", ");
    statements.push(
      `A few columns are dominated by a single value: ${parts}.`
    );
  }
  if (strongCorr.length > 0) {
    const parts = strongCorr
      .map((c) => `“${c.a}” and “${c.b}” (r = ${c.r.toFixed(2)})`)
      .join(", ");
    statements.push(
      `The strongest relationships in the data are between ${parts}.`
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>At a glance</CardTitle>
        <CardDescription>
          A plain-English summary of what this dataset looks like.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="info">
            {summary.shape?.rows?.toLocaleString() ?? "?"} rows ×{" "}
            {summary.shape?.columns ?? "?"} columns
          </Badge>
          {mix.map((m) => (
            <Badge key={m.kind} variant="secondary">
              {m.count} {m.label}
              {m.count === 1 ? "" : "s"}
            </Badge>
          ))}
        </div>
        {statements.length > 0 && (
          <ul className="space-y-1.5 text-sm text-muted">
            {statements.map((s, i) => (
              <li key={i}>• {s}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
