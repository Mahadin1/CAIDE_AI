import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getReportWithUpload } from "@/lib/queries";
import { ReportCharts } from "@/components/report/report-charts";
import { SampleNotice } from "@/components/report/sample-notice";

export const dynamic = "force-dynamic";

export default async function ReportChartsPage({
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

  return (
    <div className="space-y-8">
      <SampleNotice sample={report.sample_info_json} />
      <ReportCharts summary={report.summary_json} reportId={id} />
    </div>
  );
}
