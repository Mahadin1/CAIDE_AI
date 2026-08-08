import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/theme-toggle";
import type { Profile } from "@/lib/types";

const PLAN_LABEL: Record<string, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  scale: "Scale",
};

async function SignOutButton() {
  const signOut = async () => {
    "use server";
    const supabase = await createClient();
    await supabase.auth.signOut();
    redirect("/");
  };

  return (
    <form action={signOut}>
      <Button variant="ghost" size="sm" type="submit">
        Sign out
      </Button>
    </form>
  );
}

function initials(name: string | null | undefined, email: string | undefined): string {
  if (name) {
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map((p) => p[0])
      .join("")
      .toUpperCase();
  }
  return (email?.[0] ?? "?").toUpperCase();
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  const { data: profile } = await supabase
    .from("profiles")
    .select("*")
    .eq("id", user.id)
    .single<Profile>();

  const plan = profile?.plan ?? "free";

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur">
        <div className="container-page flex h-16 items-center justify-between">
          <Logo />
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Badge variant={plan === "free" ? "secondary" : "info"}>
              {PLAN_LABEL[plan] ?? "Free"}
              {typeof profile?.credits === "number" &&
                ` · ${profile.credits} credits`}
            </Badge>
            <Link
              href="/dashboard/account"
              className="group flex items-center gap-2"
              title={profile?.name ?? profile?.email ?? user.email}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent transition-colors group-hover:bg-accent/25">
                {initials(profile?.name, profile?.email ?? user.email)}
              </span>
            </Link>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="container-page py-10">{children}</main>
    </div>
  );
}
