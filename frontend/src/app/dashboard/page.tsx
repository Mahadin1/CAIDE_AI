import Link from "next/link";
import { Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { UploadsSection } from "@/components/dashboard/uploads-section";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { Profile, Upload } from "@/lib/types";

export const dynamic = "force-dynamic";

const PLAN_CREDITS: Record<Profile["plan"], number> = {
  free: 3,
  starter: 30,
  pro: 100,
  scale: 300,
};

export default async function DashboardPage() {
  const supabase = await createClient();

  const { data: profile } = await supabase
    .from("profiles")
    .select("id, email, plan, credits, reports_this_month")
    .single<Profile>();

  const { data: uploads } = await supabase
    .from("uploads")
    .select("*, reports(id)")
    .order("created_at", { ascending: false })
    .returns<Upload[]>();

  const plan = profile?.plan ?? "free";
  const credits = profile?.credits ?? 0;
  const allowance = PLAN_CREDITS[plan] ?? 3;
  const planLabel = plan === "free" ? "Free" : plan.charAt(0).toUpperCase() + plan.slice(1);

  return (
    <div className="space-y-10">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-medium">Dashboard</h1>
          <p className="mt-1 text-muted">
            Save a dataset, open it, and get a plain-English analysis in seconds.
          </p>
        </div>
        <Button asChild size="sm">
          <a href="#upload">
            <Plus className="h-4 w-4" /> Upload a file
          </a>
        </Button>
      </div>

      {/* Usage */}
      <Card>
        <CardContent className="flex flex-col justify-between gap-4 pt-6 md:flex-row md:items-center">
          <div>
            <p className="text-sm font-medium">
              {planLabel} plan — {credits} of {allowance} analysis credits left
              this month
            </p>
            <p className="mt-1 text-sm text-muted">
              Each analysis uses one credit. Credits reset at the start of each
              month, and upgrade to a larger plan to get more right away.
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <a href="/dashboard/account">Manage plan</a>
          </Button>
        </CardContent>
      </Card>

      {/* Upload + files + history (live client area) */}
      <UploadsSection initialUploads={uploads ?? []} />
    </div>
  );
}
