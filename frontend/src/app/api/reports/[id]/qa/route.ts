import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** Report Q&A (#8): POST a question, GET the turn history. */
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
  let body: { question?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }
  if (!body.question?.trim()) {
    return NextResponse.json(
      { detail: "question is required" },
      { status: 422 }
    );
  }

  const upstream = await fetch(
    `${backendUrl}/reports/${encodeURIComponent(id)}/qa`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.id, question: body.question }),
      cache: "no-store",
    }
  );
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}

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
    `${backendUrl}/reports/${encodeURIComponent(id)}/qa?user_id=${encodeURIComponent(user.id)}`,
    { cache: "no-store" }
  );
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
