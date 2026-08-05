import type { SupabaseClient } from "@supabase/supabase-js";

export const DIRECT_UPLOAD_LIMIT = 52_428_800; // 50 MiB (Supabase free-plan object cap)
const CHUNK_SIZE = 6 * 1024 * 1024; // 6 MiB — required by the Supabase TUS server
const PART_SIZE = 40 * 1024 * 1024; // 40 MiB parts — under the 50 MiB object cap
const MAX_PATCH_RETRIES = 4;

function b64(input: string): string {
  if (typeof btoa === "function") {
    return btoa(input);
  }
  return Buffer.from(input, "utf-8").toString("base64");
}

function tusBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!url) throw new Error("NEXT_PUBLIC_SUPABASE_URL is not configured");
  const projectId = new URL(url).hostname.split(".")[0];
  return `https://${projectId}.storage.supabase.co`;
}

function anonKey(): string {
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!key) throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is not configured");
  return key;
}

async function sessionCredentials(supabase: SupabaseClient): Promise<string> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) {
    throw new Error("No active session");
  }
  return session.access_token;
}

async function createUpload(opts: {
  baseUrl: string;
  token: string;
  bucket: string;
  path: string;
  size: number;
  contentType: string;
}): Promise<string> {
  const { baseUrl, token, bucket, path, size, contentType } = opts;
  const metadata = [
    `bucketName ${b64(bucket)}`,
    `objectName ${b64(path)}`,
    `contentType ${b64(contentType || "application/octet-stream")}`,
    `cacheControl ${b64("3600")}`,
  ].join(",");

  const res = await fetch(`${baseUrl}/storage/v1/upload/resumable`, {
    method: "POST",
    headers: {
      "Tus-Resumable": "1.0.0",
      "Upload-Length": String(size),
      "Upload-Metadata": metadata,
      Authorization: `Bearer ${token}`,
      apikey: anonKey(),
      "Content-Type": "application/json",
    },
    body: "{}",
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `Could not start resumable upload (${res.status})${body ? `: ${body}` : ""}`
    );
  }

  const location = res.headers.get("Location");
  if (!location) throw new Error("Upload did not return a location");
  return location.startsWith("http") ? location : `${baseUrl}${location}`;
}

async function headOffset(
  baseUrl: string,
  token: string,
  location: string
): Promise<number> {
  const res = await fetch(location, {
    method: "HEAD",
    headers: {
      "Tus-Resumable": "1.0.0",
      Authorization: `Bearer ${token}`,
      apikey: anonKey(),
    },
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Upload status check failed (${res.status})`);
  }
  const offset = res.headers.get("Upload-Offset");
  return offset ? Number(offset) : 0;
}

export interface ResumableUploadProgress {
  uploaded: number;
  total: number;
}

export async function uploadResumable(opts: {
  supabase: SupabaseClient;
  bucket: string;
  path: string;
  file: File | Blob;
  onProgress?: (progress: ResumableUploadProgress) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const { supabase, bucket, path, file, onProgress, signal } = opts;
  const baseUrl = tusBaseUrl();
  const token = await sessionCredentials(supabase);
  const location = await createUpload({
    baseUrl,
    token,
    bucket,
    path,
    size: file.size,
    contentType: file.type,
  });

  let offset = 0;
  const total = file.size;
  onProgress?.({ uploaded: offset, total });

  const uploadChunk = async (
    chunkOffset: number,
    body: ArrayBuffer,
    currentToken: string
  ): Promise<number> => {
    const res = await fetch(location, {
      method: "PATCH",
      headers: {
        "Tus-Resumable": "1.0.0",
        "Upload-Offset": String(chunkOffset),
        "Content-Type": "application/offset+octet-stream",
        Authorization: `Bearer ${currentToken}`,
        apikey: anonKey(),
      },
      body,
      signal,
    });
    if (res.status === 204 || res.status === 200) {
      const next = res.headers.get("Upload-Offset");
      return next ? Number(next) : chunkOffset + body.byteLength;
    }
    throw new Error(`Chunk upload failed (${res.status})`);
  };

  while (offset < total) {
    if (signal?.aborted) throw new DOMException("Upload aborted", "AbortError");

    const end = Math.min(offset + CHUNK_SIZE, total);
    const body = await file.slice(offset, end).arrayBuffer();

    let sent = false;
    let lastError: unknown = null;
    for (let attempt = 0; attempt < MAX_PATCH_RETRIES; attempt++) {
      try {
        // Token may rotate between attempts; refresh once if auth failed.
        let currentToken = token;
        if (attempt > 0) currentToken = await sessionCredentials(supabase);
        offset = await uploadChunk(offset, body, currentToken);
        sent = true;
        break;
      } catch (e) {
        lastError = e;
        if (signal?.aborted) throw e;
        // Server keeps committed bytes even if the response was lost —
        // reconcile with a HEAD before retrying.
        try {
          offset = await headOffset(baseUrl, token, location);
        } catch {
          // location may have expired; surface the original error
        }
      }
    }
    if (!sent) {
      throw lastError instanceof Error
        ? lastError
        : new Error("Could not upload file chunk");
    }
    onProgress?.({ uploaded: offset, total });
  }
}

/**
 * Uploads a file larger than the 50 MiB per-object cap by splitting it into
 * 40 MiB parts (each uploaded resumably via TUS) plus a manifest.json that
 * the backend reads to reassemble the original bytes. `path` is the folder
 * base, e.g. `uploads/{userId}/{id}-{safeName}`.
 */
export async function uploadLargeFile(opts: {
  supabase: SupabaseClient;
  bucket: string;
  path: string;
  file: File;
  onProgress?: (progress: ResumableUploadProgress) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const { supabase, bucket, path, file, onProgress, signal } = opts;
  const partCount = Math.max(1, Math.ceil(file.size / PART_SIZE));
  let uploaded = 0;

  for (let i = 0; i < partCount; i++) {
    if (signal?.aborted) throw new DOMException("Upload aborted", "AbortError");
    const start = i * PART_SIZE;
    const end = Math.min(start + PART_SIZE, file.size);
    const partPath = `${path}/part-${String(i).padStart(6, "0")}`;
    const partFile = file.slice(start, end, file.name);

    await uploadResumable({
      supabase,
      bucket,
      path: partPath,
      file: partFile,
      signal,
      onProgress: (p) =>
        onProgress?.({ uploaded: uploaded + p.uploaded, total: file.size }),
    });
    uploaded += end - start;
    onProgress?.({ uploaded, total: file.size });
  }

  const manifest = JSON.stringify({
    original_name: file.name,
    part_size: PART_SIZE,
    part_count: partCount,
    total_size: file.size,
    content_type: file.type,
  });
  const { error: manErr } = await supabase.storage
    .from(bucket)
    .upload(
      `${path}/manifest.json`,
      new Blob([manifest], { type: "application/json" }),
      { contentType: "application/json", upsert: false }
    );
  if (manErr) throw new Error(manErr.message);
}
