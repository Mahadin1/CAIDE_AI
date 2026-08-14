import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getReportWithUpload } from "@/lib/queries";
import { AdaptiveResults } from "@/components/report/adaptive-results";
import { SampleNotice } from "@/components/report/sample-notice";

export const dynamic = "force-dynamic";

export default async function ReportDeepDivePage({
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
      <AdaptiveResults summary={report.summary_json} reportId={id} />
    </div>
  );
}
