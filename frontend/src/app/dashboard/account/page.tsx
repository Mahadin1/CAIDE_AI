import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, CreditCard } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { ProfileInfo } from "@/components/account/profile-info";
import { PlanPicker } from "@/components/account/plan-picker";
import { AccountForm } from "@/components/account/account-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Profile } from "@/lib/types";

export const dynamic = "force-dynamic";

const PLAN_LABEL: Record<string, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  scale: "Scale",
};

export default async function AccountPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const { data: profile } = await supabase
    .from("profiles")
    .select("id, email, name, plan, credits, qa_credits")
    .eq("id", user.id)
    .single<Profile>();

  const plan = profile?.plan ?? "free";

  return (
    <div className="space-y-10">
      <div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Dashboard
        </Link>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-medium">Account</h1>
          <Badge variant={plan === "free" ? "secondary" : "info"}>
            {PLAN_LABEL[plan] ?? "Free"} plan
            {typeof profile?.credits === "number" &&
              ` · ${profile.credits} credits left this month`}
            {plan !== "free" &&
              typeof profile?.qa_credits === "number" &&
              ` · ${profile.qa_credits} Q&A credits`}
          </Badge>
        </div>
        <p className="mt-1 text-muted">Signed in as {profile?.email ?? user.email}</p>
      </div>

      <ProfileInfo initialName={profile?.name ?? null} email={profile?.email ?? user.email ?? ""} />

      {/* Subscription */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-4 w-4" /> Subscription
            </CardTitle>
            <CardDescription>
              Credits are per-month and reset monthly. Change your plan anytime —
              the new allowance applies immediately.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PlanPicker currentPlan={plan} />
          </CardContent>
        </Card>
      </section>

      {/* Security */}
      <AccountForm email={profile?.email ?? user.email ?? ""} />
    </div>
  );
}
