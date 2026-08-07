import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Self-serve account deletion. The backend removes all reports, uploads,
 * stored files and finally the auth user itself. Identity comes from the
 * session cookie.
 */
export async function POST() {
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

  const upstream = await fetch(`${backendUrl}/account/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: user.id }),
    cache: "no-store",
  });

  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  // The auth user is gone, so clear the session cookie and return to home.
  await supabase.auth.signOut();
  return NextResponse.json(data);
}
