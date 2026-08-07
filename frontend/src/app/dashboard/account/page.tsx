import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { AccountForm } from "@/components/account/account-form";
import type { Profile } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const { data: profile } = await supabase
    .from("profiles")
    .select("id, email, plan")
    .eq("id", user.id)
    .single<Pick<Profile, "id" | "email" | "plan">>();

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Dashboard
        </Link>
        <h1 className="mt-4 text-3xl font-medium">Account settings</h1>
        <p className="mt-1 text-muted">
          Signed in as {profile?.email ?? user.email}
          {profile?.plan === "pro" ? " · Pro plan" : " · Free plan"}
        </p>
      </div>

      <AccountForm email={profile?.email ?? user.email ?? ""} />
    </div>
  );
}
