import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Re-queues a failed analysis. Identity comes from the session cookie; the
 * upload_id must belong to the caller (the backend re-checks ownership).
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

  let body: { upload_id?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  if (!body.upload_id) {
    return NextResponse.json(
      { detail: "upload_id is required" },
      { status: 422 }
    );
  }

  const upstream = await fetch(`${backendUrl}/analyze/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: user.id, upload_id: body.upload_id }),
    cache: "no-store",
  });

  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
