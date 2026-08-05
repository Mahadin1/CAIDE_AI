"use client";

import { useMemo, useState } from "react";
import { ArrowLeft, Brain, Play } from "lucide-react";
import type { ColumnKind, PlanPreview } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

const KIND_OPTIONS: ColumnKind[] = [
  "numeric",
  "categorical",
  "date_like",
  "mixed",
  "identifier",
  "free_text",
  "boolean",
  "empty",
];

export interface Overrides {
  column_types: Record<string, ColumnKind>;
  exclude_columns: string[];
  custom_questions: string[];
}

const modeLabel: Record<string, string> = {
  full: "Full dataset",
  sample: "Sampled",
  truncated: "Truncated",
};

export function PlanPreview({
  plan,
  onStart,
  onBack,
}: {
  plan: PlanPreview;
  onStart: (overrides: Overrides) => void;
  onBack: () => void;
}) {
  const columns = useMemo(() => Object.keys(plan.column_types), [plan]);
  const [columnTypes, setColumnTypes] = useState<Record<string, ColumnKind>>({
    ...plan.column_types,
  });
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [questions, setQuestions] = useState("");

  const isSample = plan.overview.mode === "sample";
  const moe = plan.overview.sample_info?.margin_of_error;

  const buildOverrides = (): Overrides => ({
    column_types: Object.fromEntries(
      columns
        .filter((c) => !excluded.has(c))
        .map((c) => [c, columnTypes[c] ?? plan.column_types[c]])
    ),
    exclude_columns: [...excluded],
    custom_questions: questions
      .split("\n")
      .map((q) => q.trim())
      .filter(Boolean),
  });

  return (
    <div className="space-y-4">
      {/* Overview strip */}
      <div className="card-panel flex flex-wrap items-center gap-3 p-4">
        <Badge variant="info">{plan.overview.format.toUpperCase()}</Badge>
        <Badge variant="secondary">{modeLabel[plan.overview.mode]}</Badge>
        <span className="text-sm text-muted">
          {plan.overview.shape.total_rows.toLocaleString()} rows ×{" "}
          {plan.overview.shape.columns} columns
        </span>
        {plan.overview.encoding && (
          <span className="text-sm text-muted">{plan.overview.encoding}</span>
        )}
        <Badge variant="secondary" className="ml-auto">
          {plan.plan.source === "llm"
            ? "AI-planned"
            : plan.plan.source === "cache"
              ? "AI-planned (cached)"
              : "Auto plan"}
        </Badge>
      </div>

      {/* Sample notice */}
      {isSample && moe != null && (
        <div className="rounded-md border border-[#3a3320] bg-[#2a2619]/40 p-4">
          <p className="text-sm text-foreground">
            Large file — the deep analyses will run on a deterministic sample
            of {plan.overview.sample_info.sample_rows.toLocaleString()} of{" "}
            {plan.overview.sample_info.total_rows.toLocaleString()} rows.
          </p>
          <p className="mt-1 text-xs text-muted">
            Worst-case margin of error: ±{(moe * 100).toFixed(1)} pp at 95%
            confidence. Exact global stats are computed over every row.
          </p>
        </div>
      )}

      {/* Planned checks */}
      <div className="card-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Brain className="h-4 w-4 text-[#00d4ff]" />
          <h3 className="text-sm font-medium">Planned checks</h3>
        </div>
        <ul className="space-y-2">
          {plan.plan.tasks.map((task) => (
            <li key={task.id} className="flex items-start gap-2 text-sm">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#00d4ff]" />
              <div>
                <span className="text-foreground">{task.description}</span>
                {task.rationale && (
                  <p className="text-xs text-muted">{task.rationale}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>

      {/* Column types */}
      <div className="card-panel p-4">
        <h3 className="mb-3 text-sm font-medium">Column types</h3>
        <div className="space-y-2">
          {columns.map((col) => (
            <div
              key={col}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[#232a33] bg-[#1b2230] px-3 py-2"
            >
              <label className="flex min-w-0 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={excluded.has(col)}
                  onChange={(e) => {
                    const next = new Set(excluded);
                    if (e.target.checked) next.add(col);
                    else next.delete(col);
                    setExcluded(next);
                  }}
                  className="h-3.5 w-3.5 accent-[#00d4ff]"
                />
                <span
                  className={
                    excluded.has(col)
                      ? "truncate text-muted line-through"
                      : "truncate text-foreground"
                  }
                >
                  {col}
                </span>
              </label>
              <select
                disabled={excluded.has(col)}
                value={excluded.has(col) ? "empty" : (columnTypes[col] ?? "")}
                onChange={(e) =>
                  setColumnTypes((prev) => ({
                    ...prev,
                    [col]: e.target.value as ColumnKind,
                  }))
                }
                className="rounded-md border border-[#232a33] bg-[#1b2230] px-2 py-1 text-xs text-foreground focus:border-[#00d4ff] focus:outline-none disabled:opacity-50"
              >
                {KIND_OPTIONS.map((k) => (
                  <option key={k} value={k}>
                    {k.replace("_", " ")}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          Check a box to exclude a column, or change its type to steer the
          analysis.
        </p>
      </div>

      {/* Custom questions */}
      <div className="card-panel p-4">
        <h3 className="mb-1 text-sm font-medium">Questions to answer</h3>
        <p className="mb-2 text-xs text-muted">
          One per line. The agent will address these in the narrative.
        </p>
        <Textarea
          value={questions}
          onChange={(e) => setQuestions(e.target.value)}
          placeholder={"e.g. Do high-sales orders cluster in specific regions?"}
          rows={3}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2">
        <Button onClick={() => onStart(buildOverrides())} size="sm">
          <Play className="h-4 w-4" /> Start analysis
        </Button>
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
      </div>
    </div>
  );
}
