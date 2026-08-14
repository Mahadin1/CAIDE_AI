import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReportWithUpload } from "@/lib/queries";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function ReportHeader({ report }: { report: ReportWithUpload }) {
  const summary = report.summary_json;

  return (
    <div>
      <Link
        href="/dashboard/reports"
        className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Reports
      </Link>
      <div className="mt-4 flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-3xl font-medium">{report.uploads.filename}</h1>
            {report.source_format && (
              <Badge variant="secondary">{report.source_format.toUpperCase()}</Badge>
            )}
            {report.analysis_mode && (
              <Badge variant="secondary">
                {report.analysis_mode === "full"
                  ? "Full dataset"
                  : report.analysis_mode === "sample"
                    ? "Sampled"
                    : "Truncated"}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted">
            Analyzed {formatDate(report.created_at)} ·{" "}
            {summary.shape.rows.toLocaleString()} rows ×{" "}
            {summary.shape.columns} columns
            {summary.duplicate_count > 0 && (
              <> · {summary.duplicate_count.toLocaleString()} duplicate rows</>
            )}
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={`/dashboard/reports/${report.id}/export`}>
            <Download className="h-4 w-4" /> Export
          </Link>
        </Button>
      </div>
    </div>
  );
}
