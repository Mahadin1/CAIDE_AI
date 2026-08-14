import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { ProfileInfo } from "@/components/account/profile-info";
import { AccountForm } from "@/components/account/account-form";
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
          <ArrowLeft className="h-4 w-4" /> Overview
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

      {/* Security */}
      <AccountForm email={profile?.email ?? user.email ?? ""} />
    </div>
  );
}
