"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play, Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { PlanPreview, type Overrides } from "@/components/dashboard/plan-preview";
import { Button } from "@/components/ui/button";
import type { JobStatus, PlanPreview as PlanPreviewData, Upload } from "@/lib/types";

/**
 * Per-file analysis flow: "Start analysis" profiles + plans the file, lets
 * the user review/steer the plan, then queues the job and polls it to the
 * report page. Deleting the file removes it and its report from storage.
 */
export function FileAnalyze({ upload }: { upload: Upload }) {
  const router = useRouter();
  const [phase, setPhase] = useState<"idle" | "planning" | "review" | "analyzing" | "failed">("idle");
  const [plan, setPlan] = useState<PlanPreviewData | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const overridesRef = useRef<Overrides>({
    column_types: {},
    exclude_columns: [],
    custom_questions: [],
  });

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const startPlanning = async () => {
    setError(null);
    setPhase("planning");
    try {
      const res = await fetch("/api/analyze/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: upload.id,
          storage_path: upload.storage_path,
          filename: upload.filename,
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (res.status === 402) {
        setError(
          data.detail ??
            "You're out of analysis credits for this month. Manage your plan to get more."
        );
        setPhase("idle");
        return;
      }
      if (!res.ok) {
        setError(data.detail ?? "Could not prepare an analysis plan.");
        setPhase("idle");
        return;
      }

      setPlan(data as PlanPreviewData);
      setPhase("review");
    } catch {
      setError("Network error while preparing the plan. Please try again.");
      setPhase("idle");
    }
  };

  const startAnalysis = async (overrides: Overrides) => {
    if (!plan) return;
    overridesRef.current = overrides;
    setError(null);
    setPhase("analyzing");

    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        upload_id: plan.job_id,
        overrides: {
          column_types: overrides.column_types,
          exclude_columns: overrides.exclude_columns,
          custom_questions: overrides.custom_questions,
        },
      }),
    });
    const data = await res.json().catch(() => ({}));

    if (res.status === 402) {
      setError(
        data.detail ??
          "You're out of analysis credits for this month. Manage your plan to get more."
      );
      setPhase("review");
      return;
    }
    if (!res.ok) {
      setError(data.detail ?? "Analysis failed to start.");
      setPhase("review");
      return;
    }

    pollTimer.current = setInterval(async () => {
      try {
        const jr = await fetch(`/api/jobs/${plan.job_id}`);
        const j = (await jr.json()) as JobStatus;
        setJob(j);

        if (j.status === "done" && j.report_id) {
          stopPolling();
          router.push(`/dashboard/reports/${j.report_id}`);
          router.refresh();
        } else if (j.status === "failed") {
          stopPolling();
          setError(j.error_message ?? "Analysis failed. Please try again.");
          setPhase("failed");
        }
      } catch {
        // transient poll failure — keep waiting
      }
    }, 2000);
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this file and anything stored for it? This cannot be undone.")) {
      return;
    }
    setDeleting(true);
    try {
      const res = await fetch(`/api/uploads/${upload.id}/delete`, {
        method: "DELETE",
      });
      if (res.ok) {
        router.push("/dashboard");
        router.refresh();
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? "Could not delete the file.");
      }
    } finally {
      setDeleting(false);
    }
  };

  if (phase === "review" && plan) {
    return (
      <div className="space-y-4">
        <PlanPreview plan={plan} onStart={startAnalysis} onBack={() => setPhase("idle")} />
        {error && <p className="text-sm text-[#f87171]">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="card-panel flex flex-col justify-between gap-4 p-6 md:flex-row md:items-center">
        <div>
          <h2 className="font-medium">Ready when you are</h2>
          <p className="mt-1 text-sm text-muted">
            Start an analysis to profile the columns, plan the checks, and
            produce a plain-English report with charts and downloads.
          </p>
        </div>
        <Button onClick={startPlanning} disabled={phase === "planning"} size="sm">
          {phase === "planning" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {phase === "planning" ? "Planning…" : "Start analysis"}
        </Button>
      </div>

      {phase === "analyzing" && (
        <div className="card-panel p-6">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-foreground" />
            <p className="text-sm font-medium">
              {job?.stage_label ?? "Analyzing your data…"}
            </p>
          </div>
          <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${job?.progress ?? 10}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted">
            {job?.progress ?? 10}% — you can leave this page and check your
            reports later.
          </p>
        </div>
      )}

      {phase === "failed" && (
        <div className="card-panel p-6">
          <p className="text-sm font-medium text-[#f87171]">The analysis failed</p>
          {error && <p className="mt-1 text-sm text-muted">{error}</p>}
          <div className="mt-4 flex items-center gap-2">
            <Button size="sm" onClick={() => startAnalysis(overridesRef.current)}>
              <Play className="h-4 w-4" /> Try again
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPhase("idle")}>
              Back
            </Button>
          </div>
        </div>
      )}

      {error && phase !== "failed" && (
        <div className="rounded-md border border-[#3a1a1a] bg-[#3a1a1a]/40 p-4">
          <p className="text-sm text-[#f87171]">{error}</p>
          {error.includes("credits") && (
            <Button asChild size="sm" variant="secondary" className="mt-3">
              <a href="/dashboard/account">Manage plan</a>
            </Button>
          )}
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={handleDelete} disabled={deleting}>
          {deleting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
          Delete file
        </Button>
      </div>
    </div>
  );
}
