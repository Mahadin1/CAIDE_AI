import Link from "next/link";

import { Button } from "@/components/ui/button";
import { SampleReportPreview } from "@/components/landing/sample-preview";

/**
 * Hero — exactly 5 elements:
 *  1. headline
 *  2. sub-headline
 *  3. primary CTA (accent, no competing secondary CTA)
 *  4. product visual (mock report card on secondary surface)
 *  5. trust signal (small muted stat line under CTA)
 */
export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* Vercel-style glow: faint white radial at the top */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-[-320px] mx-auto h-[640px] max-w-4xl"
        style={{
          background:
            "radial-gradient(50% 50% at 50% 50%, rgba(250,250,250,0.14) 0%, rgba(250,250,250,0.05) 40%, transparent 70%)",
        }}
      />
      <div className="container-page section-padding relative grid items-center gap-16 lg:grid-cols-2">
        <div className="max-w-xl">
          <h1 className="text-4xl font-medium tracking-tight md:text-6xl">
            Turn messy CSVs into answers, not just charts.
          </h1>

          <p className="mt-6 text-lg text-muted">
            Upload any spreadsheet and get a plain-English analysis — outliers
            flagged, correlations explained, nothing left for you to interpret.
          </p>

          <div className="mt-8">
            <Button asChild size="lg">
              <Link href="/login">Analyze your first file free</Link>
            </Button>
            <p className="mt-4 text-sm text-muted">
              Trusted for 12,000+ dataset analyses
            </p>
          </div>
        </div>

        <div className="flex justify-center lg:justify-end">
          <SampleReportPreview />
        </div>
      </div>
    </section>
  );
}
