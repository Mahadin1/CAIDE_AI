import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getReportWithUpload } from "@/lib/queries";
import { ReportHeader } from "@/components/report/report-header";
import { ReportSubNav } from "@/components/report/report-subnav";

export const dynamic = "force-dynamic";

export default async function ReportLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const report = await getReportWithUpload(supabase, id);
  if (!report) notFound();

  return (
    <div className="space-y-8">
      <ReportHeader report={report} />
      <ReportSubNav reportId={id} />
      {children}
    </div>
  );
}
