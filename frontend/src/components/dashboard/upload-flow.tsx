"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, FileText, X } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn, formatBytes } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 10 * 1024 * 1024; // 10 MB

type Phase = "idle" | "uploading" | "analyzing";

interface UploadError {
  code: "limit" | "type" | "size" | "upload" | "analyze" | "auth";
  message: string;
}

export function UploadFlow() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<UploadError | null>(null);

  const pickFile = useCallback((candidate: File | undefined | null) => {
    setError(null);
    if (!candidate) return;

    if (!candidate.name.toLowerCase().endsWith(".csv")) {
      setError({ code: "type", message: "Only .csv files are supported." });
      return;
    }
    if (candidate.size > MAX_BYTES) {
      setError({
        code: "size",
        message: `That file is ${formatBytes(candidate.size)}. The limit is 10 MB.`,
      });
      return;
    }
    setFile(candidate);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      pickFile(e.dataTransfer.files?.[0]);
    },
    [pickFile]
  );

  const reset = () => {
    setFile(null);
    setError(null);
    setPhase("idle");
    if (inputRef.current) inputRef.current.value = "";
  };

  const analyze = async () => {
    if (!file) return;
    setError(null);
    setPhase("uploading");

    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      setError({ code: "auth", message: "Session expired — please sign in again." });
      setPhase("idle");
      return;
    }

    const uploadId = crypto.randomUUID();
    const storagePath = `uploads/${user.id}/${file.name}`;

    try {
      const { error: upErr } = await supabase.storage
        .from("uploads")
        .upload(storagePath, file, { upsert: false });

      if (upErr) {
        setError({
          code: "upload",
          message: upErr.message === "The resource already exists"
            ? "A file with this name already exists. Rename it and try again."
            : upErr.message,
        });
        setPhase("idle");
        return;
      }

      setPhase("analyzing");
      const res = await fetch("/api/analyze", {
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
          code: "analyze",
          message: data.detail ?? "Analysis failed. Please try again.",
        });
        setPhase("idle");
        return;
      }

      router.push(`/dashboard/reports/${data.report_id}`);
      router.refresh();
    } catch {
      setError({
        code: "analyze",
        message: "Something went wrong while analyzing. Please try again.",
      });
      setPhase("idle");
    }
  };

  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "card-panel flex cursor-pointer flex-col items-center justify-center px-6 py-12 text-center transition-colors",
          dragOver && "border-[#00d4ff]"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        {phase === "uploading" ? (
          <p className="text-sm text-muted">Uploading to secure storage…</p>
        ) : phase === "analyzing" ? (
          <p className="text-sm text-muted">
            Agent is analyzing your data… this takes a few seconds.
          </p>
        ) : (
          <>
            <UploadCloud className="h-10 w-10 text-[#00d4ff]" />
            <p className="mt-4 font-medium">Drop your CSV here, or click to browse</p>
            <p className="mt-1 text-sm text-muted">.csv only · up to 10 MB</p>
          </>
        )}
      </div>

      {file && phase === "idle" && (
        <div className="card-panel flex items-center justify-between gap-4 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <FileText className="h-5 w-5 shrink-0 text-[#00d4ff]" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted">{formatBytes(file.size)}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button onClick={analyze} size="sm">
              Analyze
            </Button>
            <Button variant="ghost" size="icon" onClick={reset} aria-label="Remove file">
              <X className="h-4 w-4" />
            </Button>
          </div>
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
