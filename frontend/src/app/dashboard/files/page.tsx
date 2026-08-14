import { createClient } from "@/lib/supabase/server";
import { getUploadsWithReports } from "@/lib/queries";
import { FilesTable } from "@/components/dashboard/files-table";

export const dynamic = "force-dynamic";

export default async function FilesPage() {
  const supabase = await createClient();
  const uploads = await getUploadsWithReports(supabase);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-medium">Files</h1>
        <p className="mt-1 text-muted">
          Upload a dataset, or open a saved one to start an analysis.
        </p>
      </div>
      <FilesTable initialUploads={uploads} />
    </div>
  );
}
