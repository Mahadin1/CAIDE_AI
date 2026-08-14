import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getReportWithUpload } from "@/lib/queries";
import { ReportFindings } from "@/components/report/report-findings";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export const dynamic = "force-dynamic";

export default async function ReportFindingsPage({
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

  const report = await getReportWithUpload(supabase, id);
  if (!report) notFound();

  const summary = report.summary_json;
  const findings = summary.findings ?? [];

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle>Findings</CardTitle>
          <CardDescription>
            {findings.length} evidence-backed issues, ranked by severity
          </CardDescription>
        </CardHeader>
        <CardContent>
          {findings.length === 0 ? (
            <p className="text-sm text-muted">
              No issues were flagged for this dataset.
            </p>
          ) : (
            <ReportFindings findings={findings} />
          )}
        </CardContent>
      </Card>

      {(summary.executed_tasks ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Checks performed</CardTitle>
            <CardDescription>The analyses the agent ran on this dataset</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {summary.executed_tasks?.map((task, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  <span className="text-muted">{task.description ?? task.type}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {(summary.skipped_tasks ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Skipped checks</CardTitle>
            <CardDescription>Analyses the agent decided were not applicable</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {summary.skipped_tasks?.map((task, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <Badge variant="secondary" className="mt-0.5">
                    {task.type}
                  </Badge>
                  <span className="text-muted">{task.reason}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
