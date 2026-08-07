import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** Changes the signed-in user's password via Supabase Auth. */
export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  let body: { password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  const password = body.password ?? "";
  if (password.length < 6) {
    return NextResponse.json(
      { detail: "New password must be at least 6 characters." },
      { status: 422 }
    );
  }

  const { error } = await supabase.auth.updateUser({ password });
  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 400 });
  }
  return NextResponse.json({ status: "ok" });
}
