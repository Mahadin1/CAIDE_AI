import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Deletes an upload history entry and its report + source file. The backend
 * checks ownership; identity comes from the session cookie.
 */
export async function DELETE(
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
    `${backendUrl}/uploads/${encodeURIComponent(id)}?user_id=${encodeURIComponent(user.id)}`,
    { method: "DELETE", cache: "no-store" }
  );

  if (upstream.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
