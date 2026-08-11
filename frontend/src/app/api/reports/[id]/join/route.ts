import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** #15 join-quality: attach a second file (already saved to storage) and
 * assess how it would merge with the report's file. */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
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

  const { id } = await params;
  let body: { storage_path?: string; params?: Record<string, unknown> };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }
  if (!body.storage_path) {
    return NextResponse.json(
      { detail: "storage_path is required" },
      { status: 422 }
    );
  }
  if (!body.storage_path.startsWith(`uploads/${user.id}/`)) {
    return NextResponse.json(
      { detail: "storage_path does not belong to this user" },
      { status: 403 }
    );
  }

  const upstream = await fetch(
    `${backendUrl}/reports/${encodeURIComponent(id)}/join`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: user.id,
        storage_path: body.storage_path,
        params: body.params ?? {},
      }),
      cache: "no-store",
    }
  );
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
