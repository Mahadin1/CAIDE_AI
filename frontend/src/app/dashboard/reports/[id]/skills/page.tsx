import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getReportWithUpload } from "@/lib/queries";
import { SkillsPanel } from "@/components/report/skills-panel";
import { UpgradePrompt } from "@/components/report/upgrade-prompt";
import { SampleNotice } from "@/components/report/sample-notice";

export const dynamic = "force-dynamic";

export default async function ReportSkillsPage({
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

  const [report, profile] = await Promise.all([
    getReportWithUpload(supabase, id),
    getProfile(supabase, user.id),
  ]);
  if (!report) notFound();

  const isPro = profile?.plan !== "free";

  return (
    <div className="space-y-8">
      <SampleNotice sample={report.sample_info_json} />
      {isPro ? (
        <SkillsPanel
          reportId={id}
          summary={report.summary_json}
          plan={profile?.plan ?? "free"}
          credits={profile?.credits ?? 0}
        />
      ) : (
        <UpgradePrompt
          title="Skills are a Pro feature"
          description="Run predictive baselines, key-driver rankings, what-if simulations and more from any report. Each run is charged from your report credits."
        />
      )}
    </div>
  );
}
