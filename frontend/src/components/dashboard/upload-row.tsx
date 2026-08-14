"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  FileCode,
  FileSpreadsheet,
  FileText,
  Loader2,
  Play,
  Download,
  Trash2,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/relative-time";
import { RowMenu, type RowMenuItem } from "@/components/dashboard/row-menu";
import type { JobStatus, Upload } from "@/lib/types";

export const statusMeta: Record<
  Upload["status"],
  { label: string; variant: "success" | "info" | "warning" | "danger" | "secondary" }
> = {
  done: { label: "Ready", variant: "success" },
  processing: { label: "Analyzing", variant: "info" },
  pending: { label: "Pending", variant: "warning" },
  ready: { label: "Saved", variant: "secondary" },
  failed: { label: "Failed", variant: "danger" },
};

export function UploadRow({
  upload,
  onStatusChange,
  href,
  extraMenuItems,
}: {
  upload: Upload;
  onStatusChange?: (id: string, status: Upload["status"] | "deleted") => void;
  href?: string;
  extraMenuItems?: RowMenuItem[];
}) {
  const [live, setLive] = useState<JobStatus | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const busy =
    (live?.status ?? upload.status) === "processing" ||
    (live?.status ?? upload.status) === "pending";

  const notify = (status: Upload["status"] | "deleted") => {
    if (status !== upload.status) onStatusChange?.(upload.id, status);
  };

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
          notify(job.status);
        }
      } catch {
        // transient — keep polling
      }
    }, 3000);
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upload.id, busy]);

  const status = live?.status ?? upload.status;
  const meta = statusMeta[status] ?? statusMeta.pending;
  const reportId = live?.report_id ?? upload.reports?.[0]?.id;
  const stageLabel = live?.stage_label ?? upload.stage_label;
  const progress = live?.progress ?? upload.progress;
  const errorMessage = live?.error_message ?? upload.error_message;

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const res = await fetch("/api/analyze/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: upload.id }),
      });
      if (res.ok) {
        onStatusChange?.(upload.id, "pending");
      } else {
        const data = await res.json().catch(() => ({}));
        setLive((prev) => ({
          ...(prev ?? ({} as JobStatus)),
          status: "failed",
          error_message: data.detail ?? "Retry failed. Please try again.",
        }));
      }
    } catch {
      // transient network error — leave the button usable
    } finally {
      setRetrying(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this analysis and its report? This cannot be undone.")) {
      return;
    }
    setDeleting(true);
    try {
      const res = await fetch(`/api/uploads/${upload.id}/delete`, {
        method: "DELETE",
      });
      if (res.ok) {
        onStatusChange?.(upload.id, "deleted");
      }
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className={cn(
        "card-panel flex items-center justify-between gap-4 p-4",
        status === "failed" && "border-[var(--danger-border)]"
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {busy ? (
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-foreground" />
        ) : (
          <FileText className="h-5 w-5 shrink-0 text-muted" />
        )}
        <div className="min-w-0">
          {href && status === "ready" ? (
            <Link
              href={href}
              className="block truncate text-sm font-medium transition-colors hover:text-accent"
            >
              {upload.filename}
            </Link>
          ) : (
            <p className="truncate text-sm font-medium">{upload.filename}</p>
          )}
          <p className="text-xs text-muted">
            <RelativeTime date={upload.created_at} />
          </p>
          {busy && stageLabel && (
            <p className="mt-0.5 text-xs text-foreground">
              {stageLabel}
              {typeof progress === "number" && ` · ${progress}%`}
            </p>
          )}
          {status === "failed" && errorMessage && (
            <p className="mt-0.5 text-xs text-[var(--danger-fg)]">{errorMessage}</p>
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

        {status === "failed" && (
          <Button onClick={handleRetry} size="sm" disabled={retrying}>
            {retrying ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Try again
          </Button>
        )}

        {status === "done" && reportId && (
          <Link
            href={`/dashboard/reports/${reportId}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-foreground hover:underline"
          >
            View report <ArrowRight className="h-4 w-4" />
          </Link>
        )}

        {!busy && (
          <RowMenu
            ariaLabel={`Options for ${upload.filename}`}
            items={[
              ...(extraMenuItems ?? []),
              ...(status === "done" && reportId
                ? [
                    {
                      label: "View report",
                      icon: <Eye className="h-4 w-4" />,
                      href: `/dashboard/reports/${reportId}`,
                    },
                    {
                      label: "Download PDF",
                      icon: <Download className="h-4 w-4" />,
                      href: `/api/reports/${reportId}/pdf`,
                      download: true,
                    },
                    {
                      label: "Download HTML",
                      icon: <FileCode className="h-4 w-4" />,
                      href: `/api/reports/${reportId}/html`,
                      download: true,
                    },
                    {
                      label: "Download cleaned CSV",
                      icon: <FileSpreadsheet className="h-4 w-4" />,
                      href: `/api/reports/${reportId}/clean`,
                      download: true,
                    },
                  ]
                : []),
              {
                label: deleting ? "Deleting…" : "Delete",
                icon: <Trash2 className="h-4 w-4" />,
                onClick: handleDelete,
                danger: true,
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
