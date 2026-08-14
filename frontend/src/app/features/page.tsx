import Link from "next/link";
import { Sparkles, Wand2 } from "lucide-react";
import { SiteNav } from "@/components/site-nav";
import { Footer } from "@/components/footer";
import { Features } from "@/components/landing/features";
import { FinalCta } from "@/components/landing/final-cta";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ADAPTIVE_TASKS, SKILLS, SKILL_ORDER } from "@/lib/skills";

export const metadata = {
  title: "Features",
};

export default function FeaturesPage() {
  return (
    <>
      <SiteNav />
      <main>
        <section className="section-padding border-b border-border">
          <div className="container-page max-w-3xl">
            <p className="text-sm font-medium uppercase tracking-widest text-muted">
              Features
            </p>
            <h1 className="mt-3 text-4xl font-medium md:text-5xl">
              An analyst&apos;s checklist, automated.
            </h1>
            <p className="mt-5 text-lg text-muted">
              DataScope reads your data like a careful analyst: profile every
              column, run the checks that matter, and explain what you should
              care about in plain English.
            </p>
            <div className="mt-8">
              <Button asChild size="lg">
                <Link href="/login">Analyze your first file free</Link>
              </Button>
            </div>
          </div>
        </section>

        <Features />

        {/* Core report */}
        <section className="section-padding border-t border-border">
          <div className="container-page">
            <p className="text-sm font-medium uppercase tracking-widest text-muted">
              Every report
            </p>
            <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
              A narrated story, not a dashboard of stats.
            </h2>
            <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {[
                {
                  t: "Plain-English narrative",
                  d: "The agent writes a report explaining what's dirty, what's correlated, and what's hiding in the tails.",
                },
                {
                  t: "Severity-ranked findings",
                  d: "Every issue is graded high / medium / low with a suggested action, so you know where to start.",
                },
                {
                  t: "Interactive charts",
                  d: "Missing values, correlations, outliers, distributions and time trends — only the ones that matter.",
                },
                {
                  t: "Column glossary",
                  d: "How every column was interpreted, so nothing is ambiguous.",
                },
                {
                  t: "Report Q&A",
                  d: "Ask follow-ups about the report and get answers grounded only in the stored analysis.",
                },
                {
                  t: "One-click exports",
                  d: "Share the report as a PDF or HTML document, or download the cleaned CSV.",
                },
              ].map((f) => (
                <div key={f.t} className="card-panel p-6">
                  <h3 className="text-lg font-medium">{f.t}</h3>
                  <p className="mt-2 text-sm text-muted">{f.d}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Adaptive deep-dives */}
        <section className="section-padding border-t border-border">
          <div className="container-page">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm font-medium uppercase tracking-widest text-muted">
                Automatic deep-dives
              </p>
              <Badge variant="secondary">All plans</Badge>
            </div>
            <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
              Six analyses run on every dataset.
            </h2>
            <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {ADAPTIVE_TASKS.map((task) => (
                <div key={task.type} className="card-panel p-6">
                  <h3 className="text-lg font-medium">{task.title}</h3>
                  <p className="mt-2 text-sm text-muted">{task.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pro skills */}
        <section className="section-padding border-t border-border">
          <div className="container-page">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm font-medium uppercase tracking-widest text-muted">
                Pro skills
              </p>
              <Badge variant="info">Pro+</Badge>
            </div>
            <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
              On-demand analyses, charged per run.
            </h2>
            <p className="mt-4 max-w-2xl text-muted">
              Run any of these against a report when you need to go deeper. Each
              skill draws from your monthly report credits.
            </p>
            <div className="mt-12 grid gap-6 md:grid-cols-2">
              {SKILL_ORDER.map((skill) => {
                const meta = SKILLS[skill];
                return (
                  <div key={skill} className="card-panel flex flex-col gap-3 p-6">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Wand2 className="h-4 w-4 text-accent" />
                        <h3 className="text-lg font-medium">{meta.label}</h3>
                      </div>
                      <Badge variant="secondary">{meta.cost} credits</Badge>
                    </div>
                    <p className="text-sm text-muted">{meta.description}</p>
                    {meta.needsBaseline && (
                      <p className="text-xs text-muted">
                        Requires a completed predictive baseline first.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mt-8">
              <Button asChild variant="outline" size="lg">
                <Link href="/pricing">
                  <Sparkles className="h-4 w-4" /> See plans &amp; pricing
                </Link>
              </Button>
            </div>
          </div>
        </section>

        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
