import { notFound } from "next/navigation";
import { Download, FileCode, FileSpreadsheet } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getProfile, getReportWithUpload } from "@/lib/queries";
import { UpgradePrompt } from "@/components/report/upgrade-prompt";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function ReportExportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) notFound();

  const [report, profile] = await Promise.all([
    getReportWithUpload(supabase, id),
    getProfile(supabase, user.id),
  ]);
  if (!report) notFound();

  const isPro = profile?.plan !== "free";

  if (!isPro) {
    return (
      <UpgradePrompt
        title="Exports are a Pro feature"
        description="Download any report as a shareable PDF or HTML document, plus the cleaned, analysis-ready CSV."
      />
    );
  }

  const exportRows: {
    title: string;
    description: string;
    icon: React.ReactNode;
    action: { label: string; href: string };
  }[] = [
    {
      title: "PDF report",
      description: "A print-ready document of the full report, charts included.",
      icon: <Download className="h-4 w-4" />,
      action: { label: "Download PDF", href: `/api/reports/${report.id}/pdf` },
    },
    {
      title: "HTML report",
      description: "The same report as a single HTML file you can host or send.",
      icon: <FileCode className="h-4 w-4" />,
      action: { label: "Download HTML", href: `/api/reports/${report.id}/html` },
    },
    {
      title: "Cleaned CSV",
      description: "Your data with the flagged issues applied — ready to reuse.",
      icon: <FileSpreadsheet className="h-4 w-4" />,
      action: {
        label: "Download CSV",
        href: `/api/reports/${report.id}/clean`,
      },
    },
  ];

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle>Export this report</CardTitle>
          <CardDescription>
            Generated from the stored analysis of {report.uploads.filename}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            {exportRows.map((row) => (
              <form
                key={row.title}
                action={row.action.href}
                method="get"
                target="_blank"
                className="card-panel flex flex-col gap-3 p-5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-muted">{row.icon}</span>
                  <h3 className="font-medium">{row.title}</h3>
                </div>
                <p className="flex-1 text-sm text-muted">{row.description}</p>
                <Button type="submit" variant="outline" size="sm" className="w-full">
                  {row.action.label}
                </Button>
              </form>
            ))}
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted">
        Exports are rendered from the analysis snapshot, so they stay stable
        even if the underlying data changes.
      </p>
    </div>
  );
}
