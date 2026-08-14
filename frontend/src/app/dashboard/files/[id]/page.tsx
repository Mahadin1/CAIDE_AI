import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, FileText } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { FileAnalyze } from "@/components/dashboard/file-analyze";
import { Badge } from "@/components/ui/badge";
import { RelativeTime } from "@/components/relative-time";
import type { Upload } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function FilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const { data: upload } = await supabase
    .from("uploads")
    .select("*, reports(id)")
    .eq("id", id)
    .eq("user_id", user.id)
    .maybeSingle<Upload>();

  if (!upload) notFound();

  const sizeMb =
    typeof upload.file_size_bytes === "number"
      ? (upload.file_size_bytes / 1024 / 1024).toFixed(2)
      : null;

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/dashboard/files"
          className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Files
        </Link>
        <div className="mt-4 flex items-center gap-3">
          <FileText className="h-6 w-6 text-muted" />
          <h1 className="text-3xl font-medium">{upload.filename}</h1>
        </div>
        <div className="mt-1 flex items-center gap-1 text-muted">
          <span>
            Saved <RelativeTime date={upload.created_at} />
          </span>
          {upload.source_format && (
            <Badge variant="secondary">{upload.source_format.toUpperCase()}</Badge>
          )}
          {sizeMb && <span>· {sizeMb} MiB</span>}
        </div>
      </div>

      <FileAnalyze upload={upload} />
    </div>
  );
}
