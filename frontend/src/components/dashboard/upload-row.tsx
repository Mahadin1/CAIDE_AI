import Link from "next/link";
import { FileText, ArrowRight } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { Upload } from "@/lib/types";

const statusMeta: Record<
  Upload["status"],
  { label: string; variant: "success" | "info" | "warning" | "danger" }
> = {
  done: { label: "Ready", variant: "success" },
  processing: { label: "Analyzing", variant: "info" },
  pending: { label: "Pending", variant: "warning" },
  failed: { label: "Failed", variant: "danger" },
};

export function UploadRow({ upload }: { upload: Upload }) {
  const meta = statusMeta[upload.status] ?? statusMeta.pending;
  const report = upload.reports?.[0];

  return (
    <div
      className={cn(
        "card-panel flex items-center justify-between gap-4 p-4",
        upload.status === "failed" && "border-[#3a1a1a]"
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <FileText className="h-5 w-5 shrink-0 text-muted" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{upload.filename}</p>
          <p className="text-xs text-muted">{timeAgo(upload.created_at)}</p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <Badge variant={meta.variant}>{meta.label}</Badge>
        {upload.status === "done" && report?.id && (
          <Link
            href={`/dashboard/reports/${report.id}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-[#00d4ff] hover:underline"
          >
            View report <ArrowRight className="h-4 w-4" />
          </Link>
        )}
      </div>
    </div>
  );
}
