import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getUploadsWithReports } from "@/lib/queries";
import { OverviewContent } from "@/components/dashboard/overview-content";
import { Button } from "@/components/ui/button";
import { planLabel, PLAN_CREDITS } from "@/lib/plan";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const [profile, uploads] = await Promise.all([
    user ? getProfile(supabase, user.id) : Promise.resolve(null),
    getUploadsWithReports(supabase),
  ]);

  const plan = profile?.plan ?? "free";
  const credits = profile?.credits ?? 0;
  const allowance = PLAN_CREDITS[plan] ?? 3;
  const firstName = profile?.name?.split(/\s+/)[0];

  return (
    <div className="space-y-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-medium">
            {firstName ? `Welcome back, ${firstName}` : "Welcome back"}
          </h1>
          <p className="mt-1 text-muted">
            Upload a dataset, open a file, or jump back into a report.
          </p>
        </div>
      </div>

      {/* Usage */}
      <div className="card-panel flex flex-col justify-between gap-4 p-5 md:flex-row md:items-center">
        <div>
          <p className="text-sm font-medium">
            {planLabel(plan)} plan — {credits} of {allowance} analysis credits
            left this month
            {plan !== "free" && (
              <> · {profile?.qa_credits ?? 0} Q&amp;A credits</>
            )}
          </p>
          <p className="mt-1 text-sm text-muted">
            Each analysis uses one credit. Credits reset monthly, and upgrading
            gets more right away.
          </p>
        </div>
        <Button asChild variant="outline" size="sm" className="shrink-0">
          <Link href="/dashboard/account/billing">Manage plan</Link>
        </Button>
      </div>

      <OverviewContent initialUploads={uploads} credits={credits} />
    </div>
  );
}
