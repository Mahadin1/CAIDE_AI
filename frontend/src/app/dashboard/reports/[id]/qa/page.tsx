import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getReportWithUpload } from "@/lib/queries";
import { ReportQa } from "@/components/report/report-qa";
import { UpgradePrompt } from "@/components/report/upgrade-prompt";

export const dynamic = "force-dynamic";

export default async function ReportQaPage({
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
      {isPro ? (
        <ReportQa reportId={id} qaCredits={profile?.qa_credits ?? 0} />
      ) : (
        <UpgradePrompt
          title="Report Q&amp;A is a Pro feature"
          description="Ask questions about this report in plain English and get answers grounded only in the stored analysis — no raw rows ever leave the dataset."
        />
      )}
    </div>
  );
}
