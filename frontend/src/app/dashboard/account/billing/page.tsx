import { notFound } from "next/navigation";
import { CreditCard, Info } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getProfile } from "@/lib/queries";
import { PlanPicker } from "@/components/account/plan-picker";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { planLabel, PLAN_CREDITS } from "@/lib/plan";

export const dynamic = "force-dynamic";

export default async function BillingPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const profile = await getProfile(supabase, user.id);
  const plan = profile?.plan ?? "free";
  const allowance = PLAN_CREDITS[plan] ?? 3;
  const credits = profile?.credits ?? 0;
  const qaCredits = profile?.qa_credits ?? 0;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-medium">Billing &amp; plan</h1>
        <p className="mt-1 text-muted">
          Credits are per-month and reset monthly. Changing plans applies the
          new allowance immediately.
        </p>
      </div>

      {/* Current cycle */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-4 w-4" /> Current cycle
          </CardTitle>
          <CardDescription>
            Your usage for the current billing month.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-border bg-elevated p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted">Plan</p>
              <p className="mt-1 flex items-center gap-2 font-medium">
                {planLabel(plan)}
                <Badge variant={plan === "free" ? "secondary" : "info"}>
                  {plan === "free" ? "Free forever" : "Active"}
                </Badge>
              </p>
            </div>
            <div className="rounded-md border border-border bg-elevated p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted">
                Analysis credits
              </p>
              <p className="mt-1 font-medium">
                {credits} of {allowance} left this month
              </p>
            </div>
            <div className="rounded-md border border-border bg-elevated p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted">Q&amp;A credits</p>
              <p className="mt-1 font-medium">
                {plan === "free" ? "—" : `${qaCredits} left this month`}
              </p>
            </div>
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-md border border-border bg-elevated p-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
            <p className="text-xs text-muted">
              A full credit-history ledger isn&apos;t available yet — this shows
              your current monthly cycle only. Credits reset at the start of
              each month.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Plan picker */}
      <Card>
        <CardHeader>
          <CardTitle>Change plan</CardTitle>
          <CardDescription>
            Upgrade or downgrade anytime — the new allowance applies right away.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PlanPicker currentPlan={plan} />
        </CardContent>
      </Card>
    </div>
  );
}
