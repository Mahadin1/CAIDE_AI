import Link from "next/link";
import { Check, Sparkles, Wand2 } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getProfile } from "@/lib/queries";
import { SKILLS, SKILL_ORDER, ADAPTIVE_TASKS } from "@/lib/skills";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function SkillsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const profile = user ? await getProfile(supabase, user.id) : null;
  const plan = profile?.plan ?? "free";
  const isPro = plan !== "free";

  return (
    <div className="space-y-12">
      <div>
        <h1 className="text-3xl font-medium">Skills</h1>
        <p className="mt-1 max-w-2xl text-muted">
          Every report already includes six automatic deep-dives. Pro plans add
          seven on-demand skills you can run against any report — each one is
          charged from your monthly report credits.
        </p>
      </div>

      {/* Adaptive deep-dives */}
      <section>
        <div className="mb-4">
          <h2 className="text-lg font-medium">Automatic deep-dives</h2>
          <p className="text-sm text-muted">
            Run on every report, included in all plans. Tier-gated server-side
            by file size.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {ADAPTIVE_TASKS.map((task) => (
            <div key={task.type} className="card-panel p-5">
              <h3 className="font-medium">{task.title}</h3>
              <p className="mt-1 text-sm text-muted">{task.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pro skills */}
      <section>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-medium">Pro skills</h2>
          <Badge variant="info">Pro+</Badge>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {SKILL_ORDER.map((skill) => {
            const meta = SKILLS[skill];
            return (
              <div key={skill} className="card-panel flex flex-col gap-3 p-5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Wand2 className="h-4 w-4 text-accent" />
                    <h3 className="font-medium">{meta.label}</h3>
                  </div>
                  <Badge variant="secondary">{meta.cost} credits</Badge>
                </div>
                <p className="flex-1 text-sm text-muted">{meta.description}</p>
                {meta.needsBaseline && (
                  <p className="text-xs text-muted">
                    Requires a completed predictive baseline first.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* How to use */}
      <section>
        <h2 className="text-lg font-medium">How to run one</h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-3">
          {[
            {
              n: "01",
              title: "Open any report",
              body: "From Files or Reports, open an analysis you want to dig into.",
            },
            {
              n: "02",
              title: "Go to the Skills tab",
              body: "Pick a skill, configure its inputs, and watch it run live.",
            },
            {
              n: "03",
              title: "Read the results",
              body: "Each run returns plain-English results, and the credit is deducted from your monthly balance.",
            },
          ].map((step) => (
            <li key={step.n} className="card-panel p-5">
              <span className="font-heading text-sm font-medium text-muted">
                {step.n}
              </span>
              <h3 className="mt-2 font-medium">{step.title}</h3>
              <p className="mt-1 text-sm text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Plan gate */}
      {!isPro && (
        <div className="card-panel flex flex-col items-center px-6 py-12 text-center">
          <Sparkles className="h-8 w-8 text-accent" />
          <h2 className="mt-4 text-xl font-medium">Skills come with Pro</h2>
          <p className="mt-2 max-w-md text-sm text-muted">
            Upgrade for predictive baselines, key-driver rankings, PSM
            comparisons and more — plus 100 analyses and 300 Q&amp;A credits
            every month.
          </p>
          <div className="mt-6 flex gap-3">
            <Button asChild size="sm">
              <Link href="/pricing">See pricing</Link>
            </Button>
          </div>
        </div>
      )}

      {isPro && (
        <div className="rounded-md border border-border bg-elevated p-4">
          <p className="flex items-center gap-2 text-sm">
            <Check className="h-4 w-4 text-accent" />
            You have {profile?.credits ?? 0} report credits left this month —
            skills draw from this balance.
          </p>
        </div>
      )}
    </div>
  );
}
