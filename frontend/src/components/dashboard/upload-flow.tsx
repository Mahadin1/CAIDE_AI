"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, FileText, X, Loader2, ArrowRight } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn, formatBytes } from "@/lib/utils";
import { uploadLargeFile, DIRECT_UPLOAD_LIMIT } from "@/lib/tus";
import { Button } from "@/components/ui/button";

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
  | "saving"
  | "saved"
  | "failed";

interface UploadError {
  code: "type" | "upload" | "save" | "auth";
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
  const [savedId, setSavedId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [resumable, setResumable] = useState(false);

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
      setPhase("idle");
      setSavedId(null);
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
    setFile(null);
    setError(null);
    setPhase("idle");
    setSavedId(null);
    setUploadProgress(0);
    setResumable(false);
    if (inputRef.current) inputRef.current.value = "";
  };

  const saveFile = async () => {
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

      setPhase("saving");
      const res = await fetch("/api/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: uploadId,
          storage_path: storagePath,
          filename: file.name,
          file_size_bytes: file.size,
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        setError({
          code: "save",
          message: data.detail ?? "Could not save the file to your Files section.",
        });
        setPhase("idle");
        return;
      }

      setSavedId(uploadId);
      setPhase("saved");
    } catch {
      setError({
        code: "upload",
        message: "Something went wrong while saving the file. Please try again.",
      });
      setPhase("idle");
    }
  };

  return (
    <div className="space-y-4">
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
          dragOver && "border-accent",
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
        {phase === "uploading" || phase === "saving" ? (
          <div className="flex w-full max-w-sm flex-col items-center gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-foreground" />
            <p className="text-sm text-muted">
              {phase === "saving"
                ? "Saving the file to your Files section…"
                : resumable
                  ? "Uploading via resumable transfer — this will resume if interrupted…"
                  : "Uploading to secure storage…"}
            </p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-border">
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{ width: `${uploadProgress || 3}%` }}
              />
            </div>
            <p className="text-xs text-muted">{uploadProgress || 0}%</p>
          </div>
        ) : (
          <>
            <UploadCloud className="h-10 w-10 text-foreground" />
            <p className="mt-4 font-medium">
              {disabled
                ? "Another analysis is running"
                : "Drop your data here, or click to browse"}
            </p>
            <p className="mt-1 text-sm text-muted">
              {disabled
                ? "Uploads are paused until the current analysis finishes."
                : `${ACCEPT_LABEL} · files up to 50 MiB upload directly, larger files use resumable multi-part transfer`}
            </p>
          </>
        )}
      </div>

      {file && phase === "idle" && (
        <div className="card-panel flex items-center justify-between gap-4 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <FileText className="h-5 w-5 shrink-0 text-foreground" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted">{formatBytes(file.size)}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button onClick={saveFile} size="sm">
              Save file
            </Button>
            <Button variant="ghost" size="icon" onClick={reset} aria-label="Remove file">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {phase === "saved" && savedId && (
        <div className="card-panel flex items-center justify-between gap-4 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <FileText className="h-5 w-5 shrink-0 text-foreground" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {file?.name} saved to your Files
              </p>
              <p className="text-xs text-muted">
                Open the file to review it, start an analysis, or delete it.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              onClick={() => router.push(`/dashboard/files/${savedId}`)}
            >
              Open file <ArrowRight className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={reset}>
              Upload another
            </Button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-[#3a1a1a] bg-[#3a1a1a]/40 p-4">
          <p className="text-sm text-[#f87171]">{error.message}</p>
        </div>
      )}
    </div>
  );
}
