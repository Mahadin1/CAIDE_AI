import type { SampleInfo } from "@/lib/types";

/** Deterministic-sampling notice, shown wherever sampled analyses appear
 *  (Overview, Deep dive, Charts). */
export function SampleNotice({ sample }: { sample: SampleInfo | null | undefined }) {
  if (!sample || sample.mode !== "sample") return null;

  return (
    <div className="rounded-md border border-border bg-elevated p-4">
      <p className="text-sm text-foreground">
        Analyzed on a deterministic sample of{" "}
        {sample.sample_rows.toLocaleString()} of{" "}
        {sample.total_rows.toLocaleString()} rows
        {typeof sample.margin_of_error === "number" && (
          <> — worst-case margin of error ±{(sample.margin_of_error * 100).toFixed(1)} pp</>
        )}{" "}
        at {Math.round((sample.confidence_level ?? 0.95) * 100)}% confidence.
      </p>
      <p className="mt-1 text-xs text-muted">
        Exact global stats were computed over every row; deep analyses use
        the sample.
      </p>
    </div>
  );
}
