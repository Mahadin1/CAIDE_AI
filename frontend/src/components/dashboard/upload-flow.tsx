"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, FileText, X, Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn, formatBytes } from "@/lib/utils";
import { uploadLargeFile, DIRECT_UPLOAD_LIMIT } from "@/lib/tus";
import { Button } from "@/components/ui/button";
import { PlanPreview, type Overrides } from "@/components/dashboard/plan-preview";
import type { JobStatus, PlanPreview as PlanPreviewData } from "@/lib/types";

const ACCEPT = [
  ".csv",
  ".tsv",
  ".xlsx",
  ".xls",
  ".ods",
  ".json",
  ".jsonl",
  ".parquet",
  ".feather",
  ".txt",
].join(",");

const ACCEPT_LABEL = "CSV · Excel · JSON · Parquet · Feather";

type Phase =
  | "idle"
  | "uploading"
  | "planning"
  | "review"
  | "analyzing"
  | "failed";

interface UploadError {
  code: "type" | "upload" | "plan" | "analyze" | "limit" | "auth";
  message: string;
}

function isSupported(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return [
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "ods",
    "json",
    "jsonl",
    "parquet",
    "feather",
    "txt",
  ].includes(ext);
}

export function UploadFlow({ disabled = false }: { disabled?: boolean }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<UploadError | null>(null);
  const [plan, setPlan] = useState<PlanPreviewData | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [resumable, setResumable] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const pickFile = useCallback(
    (candidate: File | undefined | null) => {
      if (disabled) return;
      setError(null);
      if (!candidate) return;
      if (!isSupported(candidate.name)) {
        setError({
          code: "type",
          message: `Unsupported file type. We accept ${ACCEPT_LABEL}.`,
        });
        return;
      }
      setFile(candidate);
    },
    [disabled]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      pickFile(e.dataTransfer.files?.[0]);
    },
    [disabled, pickFile]
  );

  const reset = () => {
    stopPolling();
    setFile(null);
    setError(null);
    setPhase("idle");
    setPlan(null);
    setJob(null);
    setUploadProgress(0);
    setResumable(false);
    if (inputRef.current) inputRef.current.value = "";
  };

  const uploadAndPlan = async () => {
    if (!file || disabled) return;
    setError(null);
    setPhase("uploading");

    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      setError({
        code: "auth",
        message: "Session expired — please sign in again.",
      });
      setPhase("idle");
      return;
    }

    const uploadId = crypto.randomUUID();
    const safeName = file.name.replace(/[^\w.\-]+/g, "_");
    const storagePath = `uploads/${user.id}/${uploadId.slice(0, 8)}-${safeName}`;
    const large = file.size > DIRECT_UPLOAD_LIMIT;

    try {
      if (large) {
        setResumable(true);
        setUploadProgress(0);
        await uploadLargeFile({
          supabase,
          bucket: "uploads",
          path: storagePath,
          file,
          onProgress: ({ uploaded, total }) =>
            setUploadProgress(Math.round((uploaded / total) * 100)),
        });
      } else {
        const { error: upErr } = await supabase.storage
          .from("uploads")
          .upload(storagePath, file, { upsert: false });

        if (upErr) {
          setError({ code: "upload", message: upErr.message });
          setPhase("idle");
          return;
        }
      }

      setPhase("planning");
      const res = await fetch("/api/analyze/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: uploadId,
          storage_path: storagePath,
          filename: file.name,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.status === 402) {
        setError({
          code: "limit",
          message:
            data.detail ??
            "You've used all your free reports this month. Upgrade to Pro for unlimited analyses.",
        });
        setPhase("idle");
        return;
      }

      if (!res.ok) {
        setError({
          code: "plan",
          message: data.detail ?? "Could not prepare an analysis plan.",
        });
        setPhase("idle");
        return;
      }

      setPlan(data as PlanPreviewData);
      setPhase("review");
    } catch {
      setError({
        code: "upload",
        message: "Something went wrong while preparing the file. Please try again.",
      });
      setPhase("idle");
    }
  };

  const startAnalysis = async (overrides: Overrides) => {
    if (!plan) return;
    setError(null);
    setPhase("analyzing");

    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      setError({ code: "auth", message: "Session expired — please sign in again." });
      setPhase("review");
      return;
    }

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
      setError({
        code: "limit",
        message:
          data.detail ??
          "You've used all your free reports this month. Upgrade to Pro.",
      });
      setPhase("review");
      return;
    }
    if (!res.ok) {
      setError({ code: "analyze", message: data.detail ?? "Analysis failed." });
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
          setError({
            code: "analyze",
            message: j.error_message ?? "Analysis failed. Please try again.",
          });
          setPhase("review");
        }
      } catch {
        // transient poll failure — keep waiting
      }
    }, 2000);
  };

  return (
    <div className="space-y-4">
      {phase === "review" && plan ? (
        <PlanPreview
          plan={plan}
          onStart={startAnalysis}
          onBack={reset}
        />
      ) : (
        <>
          <div
            role="button"
            tabIndex={disabled ? -1 : 0}
            onClick={() => !disabled && inputRef.current?.click()}
            onKeyDown={(e) =>
              !disabled && e.key === "Enter" && inputRef.current?.click()
            }
            onDragOver={(e) => {
              e.preventDefault();
              if (!disabled) setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={cn(
              "card-panel flex cursor-pointer flex-col items-center justify-center px-6 py-12 text-center transition-colors",
              dragOver && "border-[#fafafa]",
              disabled && "cursor-not-allowed opacity-60"
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
            {phase === "uploading" ? (
              <div className="flex w-full max-w-sm flex-col items-center gap-3">
                <Loader2 className="h-8 w-8 animate-spin text-[#fafafa]" />
                <p className="text-sm text-muted">
                  {resumable
                    ? "Uploading via resumable transfer — this will resume if interrupted…"
                    : "Uploading to secure storage…"}
                </p>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#1f1f1f]">
                  <div
                    className="h-full rounded-full bg-[#fafafa] transition-all"
                    style={{ width: `${uploadProgress || 3}%` }}
                  />
                </div>
                <p className="text-xs text-muted">{uploadProgress || 0}%</p>
              </div>
            ) : phase === "planning" ? (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="h-8 w-8 animate-spin text-[#fafafa]" />
                <p className="text-sm text-muted">
                  Profiling columns and planning the analysis…
                </p>
              </div>
            ) : (
              <>
                <UploadCloud className="h-10 w-10 text-[#fafafa]" />
                <p className="mt-4 font-medium">
                  Drop your data here, or click to browse
                </p>
                <p className="mt-1 text-sm text-muted">
                  {ACCEPT_LABEL} · files up to 50 MiB upload directly, larger files use
                  resumable multi-part transfer
                </p>
              </>
            )}
          </div>

          {file && phase === "idle" && (
            <div className="card-panel flex items-center justify-between gap-4 p-4">
              <div className="flex min-w-0 items-center gap-3">
                <FileText className="h-5 w-5 shrink-0 text-[#fafafa]" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted">{formatBytes(file.size)}</p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button onClick={uploadAndPlan} size="sm">
                  Review plan
                </Button>
                <Button variant="ghost" size="icon" onClick={reset} aria-label="Remove file">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Polling progress */}
      {phase === "analyzing" && (
        <div className="card-panel p-6">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-[#fafafa]" />
            <p className="text-sm font-medium">
              {job?.stage_label ?? "Analyzing your data…"}
            </p>
          </div>
          <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-[#1f1f1f]">
            <div
              className="h-full rounded-full bg-[#fafafa] transition-all"
              style={{ width: `${job?.progress ?? 10}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted">
            {job?.progress ?? 10}% — you can close this page and check your
            uploads later.
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-[#3a1a1a] bg-[#3a1a1a]/40 p-4">
          <p className="text-sm text-[#f87171]">{error.message}</p>
          {error.code === "limit" && (
            <Button asChild size="sm" variant="secondary" className="mt-3">
              <a href="/#pricing">Upgrade to Pro</a>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
