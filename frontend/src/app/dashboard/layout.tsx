import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getUploadsWithReports, getReportsForList } from "@/lib/queries";
import { DashboardShell } from "@/components/dashboard/dashboard-shell";

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

  const [profile, uploads, reports] = await Promise.all([
    getProfile(supabase, user.id),
    getUploadsWithReports(supabase),
    getReportsForList(supabase),
  ]);

  const signOut = async () => {
    "use server";
    const supabase = await createClient();
    await supabase.auth.signOut();
    redirect("/");
  };

  return (
    <DashboardShell
      profile={profile ?? { id: user.id, email: user.email ?? "", name: null, plan: "free", credits: 0, qa_credits: 0, reports_this_month: 0, created_at: "" }}
      uploads={uploads}
      reports={reports}
      signOut={signOut}
    >
      {children}
    </DashboardShell>
  );
}
