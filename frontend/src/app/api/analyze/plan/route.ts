import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Proxies the synchronous /analyze/plan preview to the backend. Identity
 * comes from the session cookie (never from client-supplied user_id), and
 * the storage_path must live under the caller's own folder.
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
    overrides?: Record<string, unknown>;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  const { upload_id, storage_path, filename, overrides } = body;
  if (!upload_id || !storage_path) {
    return NextResponse.json(
      { detail: "upload_id and storage_path are required" },
      { status: 422 }
    );
  }

  // Ownership guard: the storage path must live under this user's folder.
  const prefix = `uploads/${user.id}/`;
  if (!storage_path.startsWith(prefix)) {
    return NextResponse.json(
      { detail: "storage_path does not belong to this user" },
      { status: 403 }
    );
  }

  const upstream = await fetch(`${backendUrl}/analyze/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: user.id,
      upload_id,
      storage_path,
      filename: filename ?? "",
      overrides: overrides ?? {},
    }),
    cache: "no-store",
  });

  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
