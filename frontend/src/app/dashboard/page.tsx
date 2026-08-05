import Link from "next/link";
import { Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { UploadFlow } from "@/components/dashboard/upload-flow";
import { UploadRow } from "@/components/dashboard/upload-row";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { Profile, Upload } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = await createClient();

  const { data: profile } = await supabase
    .from("profiles")
    .select("id, email, plan, reports_this_month")
    .single<Profile>();

  const { data: uploads } = await supabase
    .from("uploads")
    .select("*, reports(id)")
    .order("created_at", { ascending: false })
    .returns<Upload[]>();

  const isPro = profile?.plan === "pro";
  const used = profile?.reports_this_month ?? 0;

  return (
    <div className="space-y-10">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-medium">Dashboard</h1>
          <p className="mt-1 text-muted">
            Upload a dataset and get a plain-English analysis in seconds.
          </p>
        </div>
        <Button asChild size="sm">
          <a href="#upload">
            <Plus className="h-4 w-4" /> New upload
          </a>
        </Button>
      </div>

      {/* Usage */}
      <Card>
        <CardContent className="flex flex-col justify-between gap-4 pt-6 md:flex-row md:items-center">
          <div>
            <p className="text-sm font-medium">
              {isPro
                ? "Pro plan — unlimited reports"
                : `${used} of 2 reports used this month`}
            </p>
            <p className="mt-1 text-sm text-muted">
              {isPro
                ? "Analyze as much as you like, including PDF exports."
                : "When you hit the limit, upgrade to Pro for unlimited analyses."}
            </p>
          </div>
          {!isPro && (
            <Button asChild variant="outline" size="sm">
              <a href="/#pricing">Upgrade to Pro — $12/mo</a>
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Upload */}
      <section id="upload">
        <h2 className="mb-4 text-lg font-medium">New analysis</h2>
        <UploadFlow />
      </section>

      {/* History */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">Your uploads</h2>
          {uploads && uploads.length > 0 && (
            <Badge variant="secondary">{uploads.length}</Badge>
          )}
        </div>

        {!uploads || uploads.length === 0 ? (
          <div className="card-panel p-10 text-center">
            <p className="font-medium">No analyses yet</p>
            <p className="mt-1 text-sm text-muted">
              Drop your first dataset above and the agent will build your first report.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {uploads.map((upload) => (
              <UploadRow key={upload.id} upload={upload} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
