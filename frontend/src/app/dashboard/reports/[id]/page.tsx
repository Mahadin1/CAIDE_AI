import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Download, FileCode, FileSpreadsheet } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { ReportCharts } from "@/components/report/report-charts";
import { ReportOverview } from "@/components/report/report-overview";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Plan, Profile, Report, Upload } from "@/lib/types";

export const dynamic = "force-dynamic";

interface ReportWithUpload extends Report {
  uploads: Pick<Upload, "id" | "filename" | "created_at">;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const severityStyles: Record<string, string> = {
  high: "border-[#3a1a1a] bg-[#1a0a0a]",
  medium: "border-[#3a3320] bg-[#1a160c]",
  low: "border-border bg-elevated",
  info: "border-border bg-elevated",
};

export default async function ReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const { data: report } = await supabase
    .from("reports")
    .select(
      "id, upload_id, summary_json, narrative, created_at, analysis_mode, source_format, sample_info_json, uploads(id, filename, created_at)"
    )
    .eq("id", id)
    .single<ReportWithUpload>();

  if (!report) notFound();

  const { data: profile } = await supabase
    .from("profiles")
    .select("plan")
    .single<Pick<Profile, "plan">>();

  const isPro = profile?.plan !== "free";
  const summary = report.summary_json;
  const sample = report.sample_info_json;
  const findings = summary.findings ?? [];

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Dashboard
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
          {isPro && (
            <div className="flex flex-wrap items-center gap-2">
              <form action={`/api/reports/${report.id}/pdf`} method="get" target="_blank">
                <Button type="submit" variant="outline" size="sm">
                  <Download className="h-4 w-4" /> PDF
                </Button>
              </form>
              <form action={`/api/reports/${report.id}/html`} method="get" target="_blank">
                <Button type="submit" variant="outline" size="sm">
                  <FileCode className="h-4 w-4" /> HTML
                </Button>
              </form>
              <form action={`/api/reports/${report.id}/clean`} method="get" target="_blank">
                <Button type="submit" variant="outline" size="sm">
                  <FileSpreadsheet className="h-4 w-4" /> Cleaned CSV
                </Button>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* At a glance — plain-English summary of the dataset */}
      <ReportOverview summary={summary} />

      {/* Sample notice */}
      {sample && sample.mode === "sample" && (
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
      )}

      {/* Narrative */}
      <Card>
        <CardHeader>
          <CardTitle>What the data says</CardTitle>
          <CardDescription>Generated by the DataScope analysis agent</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 text-[15px] leading-7">
            {report.narrative.split("\n").filter(Boolean).map((para, i) => (
              <p key={i}>{para}</p>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Findings */}
      {findings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Findings</CardTitle>
            <CardDescription>
              {findings.length} evidence-backed issues worth knowing about
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {findings.map((f, i) => (
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
          </CardContent>
        </Card>
      )}

      {/* Overview */}
      <Card>
        <CardHeader>
          <CardTitle>Dataset overview</CardTitle>
          <CardDescription>
            Column types detected by pandas
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {Object.entries(summary.dtypes).map(([col, dtype]) => {
            const kind = summary.column_classification?.[col]?.kind;
            const label =
              kind && kind !== "categorical" && kind !== "numeric"
                ? `${dtype} · ${kind.replace("_", " ")}`
                : dtype;
            return (
              <div
                key={col}
                className="flex items-center gap-2 rounded-md border border-border bg-elevated px-3 py-1.5"
              >
                <span className="text-sm text-foreground">{col}</span>
                <span className="text-xs text-muted">{label}</span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Charts — only the ones relevant to what was flagged */}
      <ReportCharts summary={summary} reportId={id} />
    </div>
  );
}
