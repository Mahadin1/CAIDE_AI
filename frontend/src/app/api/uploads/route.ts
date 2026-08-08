import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Proxies the save-only /uploads call to the backend so a newly uploaded
 * file lands in the Files section (status 'ready') without being analyzed.
 * Identity comes from the session cookie; the storage path must live under
 * the caller's own folder.
 */
export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    return NextResponse.json(
      { detail: "Backend is not configured" },
      { status: 503 }
    );
  }

  let body: {
    upload_id?: string;
    storage_path?: string;
    filename?: string;
    file_size_bytes?: number;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  const { upload_id, storage_path, filename, file_size_bytes } = body;
  if (!upload_id || !storage_path) {
    return NextResponse.json(
      { detail: "upload_id and storage_path are required" },
      { status: 422 }
    );
  }

  const prefix = `uploads/${user.id}/`;
  if (!storage_path.startsWith(prefix)) {
    return NextResponse.json(
      { detail: "storage_path does not belong to this user" },
      { status: 403 }
    );
  }

  const upstream = await fetch(`${backendUrl}/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: user.id,
      upload_id,
      storage_path,
      filename: filename ?? "",
      file_size_bytes: file_size_bytes ?? null,
    }),
    cache: "no-store",
  });

  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
