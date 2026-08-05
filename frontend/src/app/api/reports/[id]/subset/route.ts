import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** Proxies the backend /subset drill-down (Pro-gated server-side). */
export async function GET(
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
  const url = new URL(request.url);
  const column = url.searchParams.get("column");
  const value = url.searchParams.get("value") ?? "";
  const limit = url.searchParams.get("limit") ?? "200";
  if (!column) {
    return NextResponse.json(
      { detail: "column is required" },
      { status: 422 }
    );
  }

  const upstream = await fetch(
    `${backendUrl}/reports/${encodeURIComponent(id)}/subset?user_id=${encodeURIComponent(user.id)}&column=${encodeURIComponent(column)}&value=${encodeURIComponent(value)}&limit=${encodeURIComponent(limit)}`,
    { cache: "no-store" }
  );

  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
