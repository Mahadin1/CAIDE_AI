"use client";

import { useMemo, useState } from "react";
import { UploadFlow } from "@/components/dashboard/upload-flow";
import { UploadRow } from "@/components/dashboard/upload-row";
import { Badge } from "@/components/ui/badge";
import type { Upload } from "@/lib/types";

/**
 * Live uploads area: splits history into Analyzing / Results / Failed,
 * disables new uploads while one is running, and lets failed rows be
 * retried or deleted without leaving the page.
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
        <h2 className="mb-4 text-lg font-medium">New analysis</h2>
        <UploadFlow disabled={busy} />
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
              Drop your first dataset above and the agent will build your first report.
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
