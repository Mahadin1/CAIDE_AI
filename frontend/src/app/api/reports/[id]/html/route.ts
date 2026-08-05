import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** Proxies the backend HTML export (Pro-gated server-side). */
export async function GET(
  _request: Request,
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
  const upstream = await fetch(
    `${backendUrl}/reports/${encodeURIComponent(id)}/export/html?user_id=${encodeURIComponent(user.id)}`,
    { cache: "no-store" }
  );

  if (!upstream.ok) {
    const data = await upstream.json().catch(() => ({}));
    return NextResponse.json(data, { status: upstream.status });
  }

  const blob = await upstream.arrayBuffer();
  const contentDisposition =
    upstream.headers.get("content-disposition") ??
    'attachment; filename="report.html"';

  return new NextResponse(blob, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Disposition": contentDisposition,
    },
  });
}
