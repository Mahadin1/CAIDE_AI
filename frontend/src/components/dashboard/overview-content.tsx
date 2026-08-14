"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileBarChart, FolderOpen, Loader2, Rocket } from "lucide-react";
import { UploadFlow } from "@/components/dashboard/upload-flow";
import { UploadRow } from "@/components/dashboard/upload-row";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Upload } from "@/lib/types";

export function OverviewContent({
  initialUploads,
  credits,
}: {
  initialUploads: Upload[];
  credits: number;
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
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, status } : u)));
  };

  const recentReports = results.slice(0, 5);

  if (uploads.length === 0) {
    return (
      <div className="space-y-8">
        <section id="upload">
          <UploadFlow disabled={busy} />
        </section>

        <div className="card-panel p-10 text-center">
          <Rocket className="mx-auto h-8 w-8 text-accent" />
          <h2 className="mt-4 text-xl font-medium">Your first analysis is one upload away</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted">
            Drop in a CSV, Excel, JSON or Parquet file. DataScope profiles the
            columns, plans the checks, and writes a plain-English report with
            charts you can share.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Button size="sm" onClick={() => document.getElementById("upload")?.scrollIntoView({ behavior: "smooth" })}>
              Upload a file
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href="/features">See what you get</Link>
            </Button>
          </div>
          <div className="mx-auto mt-8 grid max-w-2xl gap-3 text-left sm:grid-cols-3">
            {[
              { n: "1", t: "Upload", d: "Any size, any common format." },
              { n: "2", t: "Review the plan", d: "Steer column types or add questions." },
              { n: "3", t: "Read the story", d: "Findings, charts and a narrative." },
            ].map((s) => (
              <div key={s.n} className="rounded-md border border-border bg-elevated p-4">
                <span className="font-heading text-sm font-medium text-muted">{s.n}</span>
                <p className="mt-1 text-sm font-medium">{s.t}</p>
                <p className="mt-0.5 text-xs text-muted">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      {/* Quick upload */}
      <section id="upload">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Quick upload</h2>
          <Button asChild variant="ghost" size="sm">
            <Link href="/dashboard/files">All files <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </div>
        <UploadFlow disabled={busy} />
      </section>

      {/* Analyzing / failed */}
      {(analyzing.length > 0 || failed.length > 0) && (
        <section>
          <h2 className="mb-3 text-lg font-medium">
            {analyzing.length > 0 ? "In progress" : "Needs attention"}
          </h2>
          <div className="space-y-3">
            {[...analyzing, ...failed].map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        </section>
      )}

      {/* Recent files */}
      {files.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-medium">Recent files</h2>
            <Button asChild variant="ghost" size="sm">
              <Link href="/dashboard/files">All files <ArrowRight className="h-4 w-4" /></Link>
            </Button>
          </div>
          <div className="space-y-3">
            {files.slice(0, 5).map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onStatusChange={handleStatusChange}
                href={`/dashboard/files/${upload.id}`}
              />
            ))}
          </div>
        </section>
      )}

      {/* Recent reports */}
      {recentReports.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-medium">Recent reports</h2>
            <Button asChild variant="ghost" size="sm">
              <Link href="/dashboard/reports">All reports <ArrowRight className="h-4 w-4" /></Link>
            </Button>
          </div>
          <div className="space-y-3">
            {recentReports.map((upload) => {
              const reportId = upload.reports?.[0]?.id;
              if (!reportId) return null;
              return (
                <Link
                  key={upload.id}
                  href={`/dashboard/reports/${reportId}`}
                  className="card-panel group flex items-center justify-between gap-4 p-4 transition-colors hover:border-[#3a3a3a]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <FileBarChart className="h-5 w-5 shrink-0 text-muted" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{upload.filename}</p>
                      <p className="text-xs text-muted">
                        <RelativeTime date={upload.created_at} />
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {upload.source_format && (
                      <Badge variant="secondary">{upload.source_format.toUpperCase()}</Badge>
                    )}
                    <ArrowRight className="h-4 w-4 text-muted transition-transform group-hover:translate-x-0.5" />
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* Quiet state */}
      {files.length === 0 && recentReports.length === 0 && (
        <div className="card-panel flex flex-col items-center p-10 text-center">
          <FolderOpen className="h-8 w-8 text-muted" />
          <p className="mt-4 font-medium">Nothing saved yet</p>
          <p className="mt-1 text-sm text-muted">
            Upload a file above to start — you have {credits} analysis credits
            left this month.
          </p>
          <Button asChild size="sm" className="mt-5">
            <Link href="/dashboard/files#upload">Go to Files</Link>
          </Button>
        </div>
      )}

      {busy && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Uploads are paused until the current analysis finishes.
        </p>
      )}
    </div>
  );
}
