import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Proxies the backend PDF export so the browser talks only to the frontend
 * origin. Identity comes from the session cookie.
 */
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
    `${backendUrl}/reports/${encodeURIComponent(id)}/pdf?user_id=${encodeURIComponent(user.id)}`,
    { cache: "no-store" }
  );

  if (!upstream.ok) {
    const data = await upstream.json().catch(() => ({}));
    return NextResponse.json(data, { status: upstream.status });
  }

  const blob = await upstream.arrayBuffer();
  const contentDisposition =
    upstream.headers.get("content-disposition") ??
    `attachment; filename="report.pdf"`;

  return new NextResponse(blob, {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": contentDisposition,
    },
  });
}
