import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Runs a user-initiated skill (predictive_baseline, psm, key_driver, what_if,
 * segment_comparison, decompose) against a report. Identity comes from the
 * session cookie; tier + credit gating happens server-side on the backend.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; skill: string }> }
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

  const { id, skill } = await params;
  let body: { params?: Record<string, unknown> };
  try {
    body = await request.json();
  } catch {
    body = { params: {} };
  }

  const upstream = await fetch(
    `${backendUrl}/reports/${encodeURIComponent(id)}/skills/${encodeURIComponent(skill)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.id, params: body.params ?? {} }),
      cache: "no-store",
    }
  );

  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
