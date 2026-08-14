import { Badge } from "@/components/ui/badge";
import type { ReportFinding } from "@/lib/types";

const severityStyles: Record<string, string> = {
  high: "border-[var(--danger-border)] bg-[var(--danger-bg)]",
  medium: "border-[var(--warning-border)] bg-[var(--warning-bg)]",
  low: "border-border bg-elevated",
  info: "border-border bg-elevated",
};

const SEVERITY_ORDER: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
  info: 3,
};

/**
 * The severity-ranked findings list. Rendered on the report Overview (top N)
 * and in full on the Findings tab.
 */
export function ReportFindings({ findings }: { findings: ReportFinding[] }) {
  if (!findings || findings.length === 0) return null;

  const sorted = [...findings].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
  );

  return (
    <div className="space-y-2">
      {sorted.map((f, i) => (
        <div
          key={i}
          className={`rounded-md border p-3 ${severityStyles[f.severity] ?? severityStyles.info}`}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-foreground">{f.message}</p>
            <Badge variant="secondary">{f.severity}</Badge>
          </div>
          {f.detail && <p className="mt-1 text-xs text-muted">{f.detail}</p>}
          {f.action && (
            <p className="mt-1 text-xs text-foreground">Suggested: {f.action}</p>
          )}
        </div>
      ))}
    </div>
  );
}
