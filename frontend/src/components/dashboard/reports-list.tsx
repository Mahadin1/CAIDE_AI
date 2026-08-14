"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Download,
  Eye,
  FileBarChart,
  FileCode,
  FileSpreadsheet,
  Search,
} from "lucide-react";
import { statusMeta } from "@/components/dashboard/upload-row";
import { RowMenu } from "@/components/dashboard/row-menu";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ReportListItem } from "@/lib/queries";

type DateFilter = "all" | "30d" | "90d" | "1y";

const DATE_FILTERS: { id: DateFilter; label: string }[] = [
  { id: "all", label: "All time" },
  { id: "30d", label: "Last 30 days" },
  { id: "90d", label: "Last 90 days" },
  { id: "1y", label: "Last year" },
];

function withinWindow(dateStr: string, days: number): boolean {
  return Date.now() - new Date(dateStr).getTime() <= days * 24 * 60 * 60 * 1000;
}

export function ReportsList({ initialReports }: { initialReports: ReportListItem[] }) {
  const [query, setQuery] = useState("");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return initialReports.filter((r) => {
      if (q && !(r.uploads?.filename ?? "").toLowerCase().includes(q)) return false;
      if (dateFilter === "30d" && !withinWindow(r.created_at, 30)) return false;
      if (dateFilter === "90d" && !withinWindow(r.created_at, 90)) return false;
      if (dateFilter === "1y" && !withinWindow(r.created_at, 365)) return false;
      return true;
    });
  }, [initialReports, query, dateFilter]);

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="relative w-full md:max-w-xs">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            placeholder="Search by file name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto rounded-md border border-border bg-surface p-1">
          {DATE_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setDateFilter(f.id)}
              className={cn(
                "whitespace-nowrap rounded px-3 py-1.5 text-sm transition-colors",
                dateFilter === f.id
                  ? "bg-elevated font-medium text-foreground"
                  : "text-muted hover:text-foreground"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Empty state */}
      {initialReports.length === 0 ? (
        <div className="card-panel p-10 text-center">
          <FileBarChart className="mx-auto h-8 w-8 text-muted" />
          <p className="mt-4 font-medium">No reports yet</p>
          <p className="mt-1 text-sm text-muted">
            Upload a file and start an analysis to generate your first report.
          </p>
          <Button asChild size="sm" className="mt-5">
            <Link href="/dashboard/files#upload">Upload a file</Link>
          </Button>
        </div>
      ) : visible.length === 0 ? (
        <div className="card-panel p-10 text-center">
          <p className="font-medium">No matching reports</p>
          <p className="mt-1 text-sm text-muted">
            Try a different search or date range.
          </p>
        </div>
      ) : (
        <div className="card-panel overflow-hidden">
          <div className="hidden grid-cols-12 gap-4 border-b border-border px-4 py-2.5 text-xs font-medium text-muted md:grid">
            <div className="col-span-5">File</div>
            <div className="col-span-2">Analyzed</div>
            <div className="col-span-3">Details</div>
            <div className="col-span-2">Actions</div>
          </div>
          <div className="divide-y divide-border">
            {visible.map((report) => {
              const meta = statusMeta[report.uploads?.status ?? "pending"] ?? statusMeta.pending;
              const shape = report.summary_json?.shape;
              return (
                <div
                  key={report.id}
                  className="grid grid-cols-12 items-center gap-4 px-4 py-3 transition-colors hover:bg-surface"
                >
                  <div className="col-span-12 min-w-0 md:col-span-5">
                    <Link
                      href={`/dashboard/reports/${report.id}`}
                      className="flex items-center gap-2 text-sm font-medium transition-colors hover:text-accent"
                    >
                      <FileBarChart className="h-4 w-4 shrink-0 text-muted" />
                      <span className="truncate">{report.uploads?.filename ?? "Report"}</span>
                    </Link>
                  </div>
                  <div className="col-span-6 text-sm text-muted md:col-span-2">
                    <RelativeTime date={report.created_at} />
                  </div>
                  <div className="col-span-6 flex flex-wrap items-center gap-1.5 md:col-span-3">
                    {report.source_format && (
                      <Badge variant="secondary">
                        {report.source_format.toUpperCase()}
                      </Badge>
                    )}
                    {report.analysis_mode && (
                      <Badge variant="secondary">
                        {report.analysis_mode === "full"
                          ? "Full"
                          : report.analysis_mode === "sample"
                            ? "Sample"
                            : "Truncated"}
                      </Badge>
                    )}
                    {shape && (
                      <span className="text-xs text-muted">
                        {shape.rows.toLocaleString()} × {shape.columns}
                      </span>
                    )}
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                  </div>
                  <div className="col-span-12 flex justify-end md:col-span-2">
                    <RowMenu
                      ariaLabel={`Options for ${report.uploads?.filename ?? "report"}`}
                      items={[
                        {
                          label: "View report",
                          icon: <Eye className="h-4 w-4" />,
                          href: `/dashboard/reports/${report.id}`,
                        },
                        {
                          label: "Download PDF",
                          icon: <Download className="h-4 w-4" />,
                          href: `/api/reports/${report.id}/pdf`,
                          download: true,
                        },
                        {
                          label: "Download HTML",
                          icon: <FileCode className="h-4 w-4" />,
                          href: `/api/reports/${report.id}/html`,
                          download: true,
                        },
                        {
                          label: "Download cleaned CSV",
                          icon: <FileSpreadsheet className="h-4 w-4" />,
                          href: `/api/reports/${report.id}/clean`,
                          download: true,
                        },
                      ]}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="text-xs text-muted">
        {visible.length} of {initialReports.length} reports shown
      </p>
    </div>
  );
}
