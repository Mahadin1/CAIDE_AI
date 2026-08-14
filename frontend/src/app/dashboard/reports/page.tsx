import { createClient } from "@/lib/supabase/server";
import { getReportsForList } from "@/lib/queries";
import { ReportsList } from "@/components/dashboard/reports-list";

export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  const supabase = await createClient();
  const reports = await getReportsForList(supabase);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-medium">Reports</h1>
        <p className="mt-1 text-muted">
          Every analysis generated for your datasets, newest first.
        </p>
      </div>
      <ReportsList initialReports={reports} />
    </div>
  );
}
