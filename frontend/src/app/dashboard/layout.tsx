import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { Profile } from "@/lib/types";

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

  return (
    <div className="min-h-screen bg-[#0b0e11]">
      <header className="sticky top-0 z-40 border-b border-[#232a33] bg-[#0b0e11]/90 backdrop-blur">
        <div className="container-page flex h-16 items-center justify-between">
          <Logo />
          <div className="flex items-center gap-4">
            <Badge variant={profile?.plan === "pro" ? "info" : "secondary"}>
              {profile?.plan === "pro" ? "Pro" : "Free"}
            </Badge>
            <span className="hidden text-sm text-muted md:block">
              {profile?.email ?? user.email}
            </span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="container-page py-10">{children}</main>
    </div>
  );
}
