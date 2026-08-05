"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FileText, ArrowRight, Loader2 } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { JobStatus, Upload } from "@/lib/types";

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
  const [live, setLive] = useState<JobStatus | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const busy =
    (live?.status ?? upload.status) === "processing" ||
    (live?.status ?? upload.status) === "pending";

  useEffect(() => {
    if (!busy) return;
    pollTimer.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${upload.id}`);
        if (!res.ok) return;
        const job = (await res.json()) as JobStatus;
        setLive(job);
        if (job.status === "done" || job.status === "failed") {
          if (pollTimer.current) clearInterval(pollTimer.current);
        }
      } catch {
        // transient — keep polling
      }
    }, 3000);
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [upload.id, busy]);

  const status = live?.status ?? upload.status;
  const meta = statusMeta[status] ?? statusMeta.pending;
  const reportId = live?.report_id ?? upload.reports?.[0]?.id;
  const stageLabel = live?.stage_label ?? upload.stage_label;
  const progress = live?.progress ?? upload.progress;
  const errorMessage = live?.error_message ?? upload.error_message;

  return (
    <div
      className={cn(
        "card-panel flex items-center justify-between gap-4 p-4",
        status === "failed" && "border-[#3a1a1a]"
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {busy ? (
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[#fafafa]" />
        ) : (
          <FileText className="h-5 w-5 shrink-0 text-muted" />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{upload.filename}</p>
          <p className="text-xs text-muted">{timeAgo(upload.created_at)}</p>
          {busy && stageLabel && (
            <p className="mt-0.5 text-xs text-[#fafafa]">
              {stageLabel}
              {typeof progress === "number" && ` · ${progress}%`}
            </p>
          )}
          {status === "failed" && errorMessage && (
            <p className="mt-0.5 text-xs text-[#f87171]">{errorMessage}</p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {upload.source_format && status === "done" && (
          <Badge variant="secondary">
            {upload.source_format.toUpperCase()}
          </Badge>
        )}
        {upload.analysis_mode && status === "done" && (
          <Badge variant="secondary">
            {upload.analysis_mode === "full"
              ? "Full"
              : upload.analysis_mode === "sample"
                ? "Sample"
                : "Truncated"}
          </Badge>
        )}
        <Badge variant={meta.variant}>{meta.label}</Badge>
        {status === "done" && reportId && (
          <Link
            href={`/dashboard/reports/${reportId}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-[#fafafa] hover:underline"
          >
            View report <ArrowRight className="h-4 w-4" />
          </Link>
        )}
      </div>
    </div>
  );
}
