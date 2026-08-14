import { createClient } from "@/lib/supabase/server";
import type { Profile, Report, Upload } from "@/lib/types";

export type SupabaseServerClient = Awaited<ReturnType<typeof createClient>>;

/** A report with enough of its parent upload to render headers and lists. */
export interface ReportWithUpload extends Report {
  uploads: Pick<Upload, "id" | "filename" | "created_at" | "status">;
}

/** A report row for the top-level Reports list. */
export interface ReportListItem {
  id: string;
  upload_id: string;
  created_at: string;
  analysis_mode?: "full" | "sample" | "truncated" | null;
  source_format?: string | null;
  summary_json?: { shape?: { rows: number; columns: number } } | null;
  uploads: Pick<Upload, "id" | "filename" | "created_at" | "status">;
}

export async function getProfile(
  supabase: SupabaseServerClient,
  userId: string
): Promise<Profile | null> {
  const { data } = await supabase
    .from("profiles")
    .select("id, email, name, plan, credits, qa_credits, reports_this_month")
    .eq("id", userId)
    .single<Profile>();
  return data;
}

export async function getReportWithUpload(
  supabase: SupabaseServerClient,
  reportId: string
): Promise<ReportWithUpload | null> {
  const { data } = await supabase
    .from("reports")
    .select(
      "id, upload_id, summary_json, narrative, created_at, analysis_mode, source_format, sample_info_json, column_glossary, uploads(id, filename, created_at, status)"
    )
    .eq("id", reportId)
    .single<ReportWithUpload>();
  return data;
}

export async function getUploadsWithReports(
  supabase: SupabaseServerClient
): Promise<Upload[]> {
  const { data } = await supabase
    .from("uploads")
    .select("*, reports(id)")
    .order("created_at", { ascending: false })
    .returns<Upload[]>();
  return data ?? [];
}

export async function getReportsForList(
  supabase: SupabaseServerClient
): Promise<ReportListItem[]> {
  const { data } = await supabase
    .from("reports")
    .select(
      "id, upload_id, summary_json, created_at, analysis_mode, source_format, uploads(id, filename, created_at, status)"
    )
    .order("created_at", { ascending: false })
    .returns<ReportListItem[]>();
  return data ?? [];
}
