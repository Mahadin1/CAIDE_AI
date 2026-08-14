"use client";

import { useMemo, useState } from "react";
import { FolderOpen, Loader2 } from "lucide-react";
import { UploadFlow } from "@/components/dashboard/upload-flow";
import { UploadRow } from "@/components/dashboard/upload-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Upload } from "@/lib/types";

type Filter = "all" | "ready" | "analyzing" | "done" | "failed";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "ready", label: "Saved" },
  { id: "analyzing", label: "Analyzing" },
  { id: "done", label: "Reports" },
  { id: "failed", label: "Failed" },
];

export function FilesTable({ initialUploads }: { initialUploads: Upload[] }) {
  const [uploads, setUploads] = useState<Upload[]>(initialUploads);
  const [filter, setFilter] = useState<Filter>("all");

  const analyzing = useMemo(
    () => uploads.filter((u) => u.status === "pending" || u.status === "processing"),
    [uploads]
  );
  const busy = analyzing.length > 0;

  const counts: Record<Filter, number> = useMemo(
    () => ({
      all: uploads.length,
      ready: uploads.filter((u) => u.status === "ready").length,
      analyzing: analyzing.length,
      done: uploads.filter((u) => u.status === "done").length,
      failed: uploads.filter((u) => u.status === "failed").length,
    }),
    [uploads, analyzing]
  );

  const visible = useMemo(() => {
    if (filter === "all") return uploads;
    if (filter === "analyzing")
      return uploads.filter((u) => u.status === "pending" || u.status === "processing");
    return uploads.filter((u) => u.status === filter);
  }, [uploads, filter]);

  const handleStatusChange = (id: string, status: Upload["status"] | "deleted") => {
    if (status === "deleted") {
      setUploads((prev) => prev.filter((u) => u.id !== id));
      return;
    }
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, status } : u)));
  };

  return (
    <div className="space-y-8">
      {/* Upload */}
      <section id="upload">
        <h2 className="mb-3 text-lg font-medium">Upload a dataset</h2>
        <UploadFlow disabled={busy} />
      </section>

      {/* Filter tabs */}
      <div className="flex gap-1 overflow-x-auto rounded-md border border-border bg-surface p-1">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={cn(
              "flex items-center gap-1.5 whitespace-nowrap rounded px-3 py-1.5 text-sm transition-colors",
              filter === f.id
                ? "bg-elevated font-medium text-foreground"
                : "text-muted hover:text-foreground"
            )}
          >
            {f.label}
            <Badge variant="secondary">{counts[f.id]}</Badge>
          </button>
        ))}
      </div>

      {/* Table */}
      {uploads.length === 0 ? (
        <div className="card-panel p-10 text-center">
          <FolderOpen className="mx-auto h-8 w-8 text-muted" />
          <p className="mt-4 font-medium">No files yet</p>
          <p className="mt-1 text-sm text-muted">
            Uploaded datasets are saved here. Open one to start an analysis.
          </p>
        </div>
      ) : visible.length === 0 ? (
        <div className="card-panel p-10 text-center">
          <p className="font-medium">Nothing here</p>
          <p className="mt-1 text-sm text-muted">
            No files match the {FILTERS.find((f) => f.id === filter)?.label} filter.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((upload) => (
            <UploadRow
              key={upload.id}
              upload={upload}
              onStatusChange={handleStatusChange}
              href={upload.status === "ready" ? `/dashboard/files/${upload.id}` : undefined}
              extraMenuItems={
                upload.status === "ready"
                  ? [
                      {
                        label: "Open file",
                        icon: <FolderOpen className="h-4 w-4" />,
                        href: `/dashboard/files/${upload.id}`,
                      },
                    ]
                  : undefined
              }
            />
          ))}
        </div>
      )}

      {busy && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Uploads are paused until the current analysis finishes.
        </p>
      )}

      {uploads.length > 0 && (
        <div className="flex justify-end">
          <Button asChild variant="ghost" size="sm">
            <a href="/dashboard/reports">Browse all reports →</a>
          </Button>
        </div>
      )}
    </div>
  );
}
