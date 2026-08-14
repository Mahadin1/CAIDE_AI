"use client";

import { useEffect, useState } from "react";
import { X, Loader2, Table2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface SubsetResponse {
  column: string;
  value: string;
  rows: Record<string, string | number | boolean | null>[];
  count: number;
}

export function RowDrilldown({
  reportId,
  column,
  value,
  title,
  onClose,
  useIndices = false,
}: {
  reportId: string;
  column: string;
  value: string;
  title: string;
  onClose: () => void;
  useIndices?: boolean;
}) {
  const [data, setData] = useState<SubsetResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams();
    if (useIndices) {
      params.set("indices", value);
    } else {
      params.set("column", column);
      params.set("value", value);
    }
    params.set("limit", "200");
    fetch(`/api/reports/${reportId}/subset?${params.toString()}`)
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.detail ?? "Could not load rows");
        if (active) setData(body);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "Could not load rows");
      });
    return () => {
      active = false;
    };
  }, [reportId, column, value, useIndices]);

  const rows = data?.rows ?? [];
  const columns = rows.length > 0 ? Object.keys(rows[0]) : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-border bg-surface"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Table2 className="h-4 w-4 shrink-0 text-muted" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{title}</p>
              <p className="text-xs text-muted">
                {useIndices
                  ? `First ${data?.count ?? 0} of the requested row positions`
                  : `${column} = “${value}”`}
                {data && data.count > 0 && !useIndices && ` · first ${data.count} of the matching rows`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted transition-colors hover:bg-elevated hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {error ? (
            <div className="p-8 text-center text-sm text-[var(--danger-fg)]">{error}</div>
          ) : !data ? (
            <div className="flex flex-col items-center gap-2 p-8 text-sm text-muted">
              <Loader2 className="h-5 w-5 animate-spin text-foreground" />
              Loading rows…
            </div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted">
              No rows matched {column} = “{value}”.
            </div>
          ) : (
            <table className="w-full border-collapse text-left text-sm">
              <thead className="sticky top-0 bg-elevated">
                <tr>
                  {columns.map((c) => (
                    <th
                      key={c}
                      className="whitespace-nowrap border-b border-border px-4 py-2 text-xs font-medium text-muted"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b border-border/60 last:border-0">
                    {columns.map((c) => (
                      <td key={c} className="whitespace-nowrap px-4 py-1.5">
                        {row[c] === null || row[c] === undefined ? (
                          <span className="text-muted">—</span>
                        ) : (
                          String(row[c])
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <Badge variant="secondary">
            {data ? `${data.count} row${data.count === 1 ? "" : "s"}` : "…"}
          </Badge>
          <button
            onClick={onClose}
            className="text-sm text-muted transition-colors hover:text-foreground"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
