import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** Skill-run history for a report (own rows only). */
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
    `${backendUrl}/reports/${encodeURIComponent(id)}/skills?user_id=${encodeURIComponent(user.id)}`,
    { cache: "no-store" }
  );
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
