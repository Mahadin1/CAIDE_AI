"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { FileText, ArrowRight } from "lucide-react";
import { UploadFlow } from "@/components/dashboard/upload-flow";
import { UploadRow } from "@/components/dashboard/upload-row";
import { Badge } from "@/components/ui/badge";
import type { Upload } from "@/lib/types";

/**
 * Live uploads area: splits history into Files (saved, status 'ready'),
 * Analyzing, Failed and Results. Uploads are paused while one is running.
 * Saved files are clickable and open their own page where the user decides
 * what to do with them.
 */
export function UploadsSection({
  initialUploads,
}: {
  initialUploads: Upload[];
}) {
  const [uploads, setUploads] = useState<Upload[]>(initialUploads);

  const analyzing = useMemo(
    () => uploads.filter((u) => u.status === "pending" || u.status === "processing"),
    [uploads]
  );
  const files = useMemo(() => uploads.filter((u) => u.status === "ready"), [uploads]);
  const results = useMemo(() => uploads.filter((u) => u.status === "done"), [uploads]);
  const failed = useMemo(() => uploads.filter((u) => u.status === "failed"), [uploads]);

  const busy = analyzing.length > 0;

  const handleStatusChange = (id: string, status: Upload["status"] | "deleted") => {
    if (status === "deleted") {
      setUploads((prev) => prev.filter((u) => u.id !== id));
      return;
    }
    setUploads((prev) =>
      prev.map((u) => (u.id === id ? { ...u, status } : u))
    );
  };

  return (
    <div className="space-y-10">
      {/* Upload */}
      <section id="upload">
        <h2 className="mb-4 text-lg font-medium">Upload a dataset</h2>
        <UploadFlow disabled={busy} />
      </section>

      {/* Files — saved but not analyzed */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">Your files</h2>
          {files.length > 0 && <Badge variant="secondary">{files.length}</Badge>}
        </div>

        {files.length === 0 ? (
          <div className="card-panel p-10 text-center">
            <p className="font-medium">No files yet</p>
            <p className="mt-1 text-sm text-muted">
              Uploaded datasets are saved here. Open one to start an analysis.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {files.map((upload) => (
              <Link
                key={upload.id}
                href={`/dashboard/files/${upload.id}`}
                className="card-panel group flex items-center justify-between gap-4 p-4 transition-colors hover:border-[#3a3a3a]"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <FileText className="h-5 w-5 shrink-0 text-muted" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{upload.filename}</p>
                    <p className="text-xs text-muted">
                      {upload.source_format?.toUpperCase() ?? "File"}
                      {typeof upload.file_size_bytes === "number" &&
                        ` · ${(upload.file_size_bytes / 1024 / 1024).toFixed(2)} MiB`}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant="secondary">Saved</Badge>
                  <ArrowRight className="h-4 w-4 text-muted transition-transform group-hover:translate-x-0.5" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Analyzing */}
      {analyzing.length > 0 && (
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Analyzing</h2>
            <Badge variant="secondary">{analyzing.length}</Badge>
          </div>
          <div className="space-y-3">
            {analyzing.map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        </section>
      )}

      {/* Failed */}
      {failed.length > 0 && (
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Needs attention</h2>
            <Badge variant="secondary">{failed.length}</Badge>
          </div>
          <div className="space-y-3">
            {failed.map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        </section>
      )}

      {/* Results */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">Your reports</h2>
          {results.length > 0 && <Badge variant="secondary">{results.length}</Badge>}
        </div>

        {uploads.length === 0 ? (
          <div className="card-panel p-10 text-center">
            <p className="font-medium">No analyses yet</p>
            <p className="mt-1 text-sm text-muted">
              Save a file above, open it, and start your first analysis.
            </p>
          </div>
        ) : results.length === 0 ? (
          <div className="card-panel p-10 text-center">
            <p className="font-medium">No completed reports yet</p>
            <p className="mt-1 text-sm text-muted">
              Finished analyses appear here with their charts and downloads.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {results.map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
