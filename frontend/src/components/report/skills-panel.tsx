"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, Play } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";
import { SKILLS, SKILL_ORDER } from "@/lib/skills";
import type { SkillRun, Summary, UserSkill } from "@/lib/types";

function fmt(x: unknown, nd = 2): string {
  if (typeof x !== "number" || Number.isNaN(x)) return "—";
  return x.toFixed(nd);
}
function pct(x: unknown): string {
  if (typeof x !== "number" || Number.isNaN(x)) return "—";
  return `${Math.round(x * 1000) / 10}%`;
}

/* ------------------------------------------------------------------ */
/* Small result renderers                                              */
/* ------------------------------------------------------------------ */

function MetricGrid({ metrics }: { metrics: Record<string, unknown> }) {
  const rows: [string, unknown][] = Object.entries(metrics ?? {});
  if (!rows.length) return null;
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
      {rows.map(([k, v]) => (
        <div key={k} className="rounded-md border border-border bg-elevated px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-muted">{k.replace(/_/g, " ")}</p>
          <p className="text-sm font-medium">{typeof v === "number" ? fmt(v, 3) : String(v)}</p>
        </div>
      ))}
    </div>
  );
}

function PsmCaveat({ caveat }: { caveat: { text?: string; non_suppressible?: boolean } }) {
  return (
    <div className="mt-3 rounded-md border-2 border-[#f87171]/60 bg-[#2a0a0a] p-4" data-testid="psm-caveat">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#f87171]" />
        <div>
          <p className="text-sm font-medium text-[#f87171]">
            This is an association, not proof of causation
          </p>
          <p className="mt-1 text-xs text-muted">{caveat.text}</p>
        </div>
      </div>
    </div>
  );
}

function ResultView({ result }: { result: Record<string, unknown> }) {
  if (result.skipped) {
    return (
      <p className="mt-2 text-sm text-muted">Not applicable: {String(result.reason)}</p>
    );
  }
  if ("att_estimate" in result) {
    return (
      <div className="mt-3 space-y-3">
        <MetricGrid
          metrics={{
            att_estimate: result.att_estimate,
            matched_pairs: result.matched_pairs,
            raw_group_difference: result.raw_group_difference,
            balance_before_smd: result.balance_before_smd,
            balance_after_smd: result.balance_after_smd,
          }}
        />
        <p className="text-xs text-muted">
          {fmt(result.matched_pairs, 0)} matched pairs · treated={fmt(result.raw_rows_treated, 0)} · control={fmt(result.raw_rows_control, 0)}. Balance after matching should be well below the before value.
        </p>
        {result.caveat && typeof result.caveat === "object" ? (
          <PsmCaveat caveat={result.caveat as { text?: string; non_suppressible?: boolean }} />
        ) : null}
      </div>
    );
  }
  if ("permutation_importance" in result || "drivers" in result) {
    const drivers = (result.permutation_importance ?? result.drivers) as
      | { feature: string; importance: number }[]
      | undefined;
    return (
      <div className="mt-3 space-y-3">
        <MetricGrid
          metrics={
            (result.metrics as Record<string, unknown> | undefined) ??
            (result.holdout_metrics as Record<string, unknown> | undefined) ??
            {}
          }
        />
        {drivers && drivers.length > 0 && (
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {drivers.slice(0, 8).map((d) => (
              <li key={d.feature}>
                <strong>{d.feature}</strong> — {fmt(d.importance, 3)}
              </li>
            ))}
          </ol>
        )}
      </div>
    );
  }
  if ("prediction" in result || "probability_positive_class" in result) {
    const r = result.result as Record<string, unknown> | undefined;
    const target = r ?? result;
    return (
      <div className="mt-3">
        <MetricGrid
          metrics={{
            prediction: target.prediction,
            lower: target.lower,
            upper: target.upper,
            probability: target.probability_positive_class,
            predicted_class: target.predicted_class,
          }}
        />
        {target.interval_note ? (
          <p className="mt-2 text-xs text-muted">{String(target.interval_note)}</p>
        ) : null}
      </div>
    );
  }
  if ("p_value" in result) {
    return (
      <div className="mt-3 space-y-2">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary">p = {fmt(result.p_value, 4)}</Badge>
          <Badge variant="secondary">Cohen&apos;s d = {fmt(result.effect_size_d)}</Badge>
          <Badge variant="secondary">n = {fmt(result.rows_a, 0)} / {fmt(result.rows_b, 0)}</Badge>
        </div>
        <p className="text-sm">
          {result.significant
            ? "There is a statistically significant difference between the two segments."
            : "No statistically significant difference was detected."}
        </p>
        <p className="text-xs text-muted">Mean {fmt(result.mean_a)} vs {fmt(result.mean_b)}</p>
      </div>
    );
  }
  if ("total_change" in result) {
    return (
      <div className="mt-3 space-y-2">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["Total change", fmt(result.total_change)],
            ["Within", fmt(result.within_effect)],
            ["Mix", fmt(result.mix_effect)],
            ["Interaction", fmt(result.interaction)],
          ].map(([k, v]) => (
            <div key={k} className="rounded-md border border-border bg-elevated px-3 py-2">
              <p className="text-[11px] uppercase tracking-wide text-muted">{k}</p>
              <p className="text-sm font-medium">{v}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted">
          {result.per_segment && Array.isArray(result.per_segment)
            ? `${result.per_segment.length} segment(s) with both-period data contributed.`
            : ""}
        </p>
      </div>
    );
  }
  if ("left_file" in result) {
    const l = result.left_file as Record<string, Record<string, unknown>>;
    const r = result.right_file as Record<string, Record<string, unknown>>;
    return (
      <div className="mt-3 space-y-3">
        <p className="text-sm">{String(result.verdict)}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ["Analyzed file", l],
              ["Second file", r],
            ] as [string, Record<string, Record<string, unknown>>][]
          ).map(([name, side]) => (
            <div key={String(name)} className="rounded-md border border-border bg-elevated p-3">
              <p className="text-xs font-medium text-muted">{String(name)} ({String(side.key_column)})</p>
              <div className="mt-1 grid grid-cols-2 gap-1 text-sm">
                <span>Matched</span><span className="text-right">{pct(side.matched_pct)}</span>
                <span>Orphaned</span><span className="text-right">{pct(side.orphaned_pct)}</span>
                <span>Dup keys</span><span className="text-right">{fmt((side.summary as Record<string, unknown>)?.duplicate_key_rows, 0)} rows</span>
                <span>Max fanout</span><span className="text-right">{fmt((side.summary as Record<string, unknown>)?.max_fanout_for_key, 0)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return <pre className="mt-3 max-h-72 overflow-auto rounded border border-border bg-elevated p-3 text-xs">{JSON.stringify(result, null, 2)}</pre>;
}

/* ------------------------------------------------------------------ */
/* The panel                                                           */
/* ------------------------------------------------------------------ */

export function SkillsPanel({
  reportId,
  summary,
  plan,
  credits,
  qaGated = true,
}: {
  reportId: string;
  summary: Summary;
  plan: string;
  credits: number;
  qaGated?: boolean;
}) {
  const [runs, setRuns] = useState<SkillRun[]>([]);
  const [busy, setBusy] = useState<UserSkill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{ skill: UserSkill; result: Record<string, unknown> } | null>(null);
  const [expanded, setExpanded] = useState<UserSkill | null>(null);

  const refreshRuns = useCallback(() => {
    fetch(`/api/reports/${reportId}/skills`)
      .then((res) => res.json())
      .then((body) => setRuns(body.runs ?? []))
      .catch(() => {});
  }, [reportId]);

  useEffect(refreshRuns, [refreshRuns]);

  const isPro = plan !== "free";
  const hasBaseline = runs.some(
    (r) => r.skill === "predictive_baseline" && r.status === "done"
  );

  const run = async (skill: UserSkill, params: Record<string, unknown>) => {
    setError(null);
    setBusy(skill);
    setLastResult(null);
    try {
      const res = await fetch(`/api/reports/${reportId}/skills/${skill}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? `Could not run ${skill}`);
      }
      if (body.status === "skipped") {
        setLastResult({ skill, result: { skipped: true, reason: body.reason } });
      } else if (body.status === "done") {
        setLastResult({ skill, result: body.result });
      }
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Skill run failed");
    } finally {
      setBusy(null);
    }
  };

  if (!isPro) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Advanced skills</CardTitle>
          <CardDescription>
            Deep-dive analyses (predictive baselines, treatment comparison, key drivers,
            what-if, segment comparison, decomposition, join quality) require the Pro or
            Scale plan.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Advanced skills</CardTitle>
        <CardDescription>
          Pro+ features, each charged separately from your report credits. You have{" "}
          <strong>{credits}</strong> credit{credits === 1 ? "" : "s"}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {SKILL_ORDER.map((skill) => {
          const info = SKILLS[skill];
          const locked = skill === "what_if" && !hasBaseline;
          return (
            <div key={skill} className="rounded-md border border-border bg-elevated/40 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{info.label}</p>
                    <Badge variant="secondary">{info.cost} credits</Badge>
                    {locked && <Badge variant="outline">needs baseline</Badge>}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{info.description}</p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setExpanded(expanded === skill ? null : skill)}
                >
                  {expanded === skill ? "Hide" : "Configure"}
                </Button>
              </div>

              {expanded === skill && (
                <div className="mt-3 border-t border-border pt-3">
                  {locked ? (
                    <p className="text-sm text-muted">
                      Run the predictive baseline first — the what-if simulator scores
                      scenarios against that model.
                    </p>
                  ) : (
                    <SkillForm
                      skill={skill}
                      summary={summary}
                      busy={busy === skill}
                      onRun={(params) => run(skill, params)}
                    />
                  )}
                </div>
              )}

              {lastResult?.skill === skill && <ResultView result={lastResult.result} />}
            </div>
          );
        })}

        {error && (
          <div className="rounded-md border border-[#3a1a1a] bg-[#3a1a1a]/40 p-3">
            <p className="text-sm text-[#f87171]">{error}</p>
          </div>
        )}

        {runs.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Recent runs</p>
            <div className="space-y-1">
              {runs.slice(0, 6).map((r) => (
                <div key={r.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-muted">{SKILLS[r.skill]?.label ?? r.skill}</span>
                  <span className="flex items-center gap-2">
                    <Badge variant={r.status === "done" ? "secondary" : "outline"}>{r.status}</Badge>
                    <span className="text-xs text-muted">{new Date(r.created_at).toLocaleDateString()}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Per-skill configuration form                                        */
/* ------------------------------------------------------------------ */

function SkillForm({
  skill,
  summary,
  busy,
  onRun,
}: {
  skill: UserSkill;
  summary: Summary;
  busy: boolean;
  onRun: (params: Record<string, unknown>) => void;
}) {
  const numericCols = Object.keys(summary.numeric_stats ?? {});
  const allCols = Object.keys(summary.column_classification ?? {});
  const categoricalCols = Object.entries(summary.column_classification ?? {})
    .filter(([, info]) => info.kind === "categorical")
    .map(([c]) => c);
  const dateCols = Object.entries(summary.column_classification ?? {})
    .filter(([, info]) => info.kind === "date_like")
    .map(([c]) => c);

  const [target, setTarget] = useState(numericCols[0] ?? "");
  const [treatment, setTreatment] = useState(categoricalCols[0] ?? "");
  const [outcome, setOutcome] = useState(numericCols[0] ?? "");
  const [metric, setMetric] = useState(numericCols[0] ?? "");
  const [segColA, setSegColA] = useState("");
  const [segValA, setSegValA] = useState("");
  const [segColB, setSegColB] = useState("");
  const [segValB, setSegValB] = useState("");
  const [metricCol, setMetricCol] = useState(numericCols[0] ?? "");
  const [dateCol, setDateCol] = useState(dateCols[0] ?? "");
  const [segmentCol, setSegmentCol] = useState(categoricalCols[0] ?? "");
  const [leftKey, setLeftKey] = useState("");
  const [rightKey, setRightKey] = useState("");
  const [secondFile, setSecondFile] = useState<File | null>(null);
  const [secondPath, setSecondPath] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [scenarioFields, setScenarioFields] = useState<Record<string, string>>({});
  const [baselineTarget, setBaselineTarget] = useState(target);

  const handleRun = () => {
    if (skill === "predictive_baseline") {
      onRun({ target_column: target });
    } else if (skill === "psm") {
      onRun({ treatment_column: treatment, outcome_column: outcome });
    } else if (skill === "key_driver") {
      onRun({ target_column: target });
    } else if (skill === "what_if") {
      const scenario: Record<string, unknown> = {};
      for (const [col, v] of Object.entries(scenarioFields)) {
        const parsed = Number(v);
        scenario[col] = Number.isNaN(parsed) || v === "" ? v : parsed;
      }
      onRun({ target_column: baselineTarget, scenario });
    } else if (skill === "segment_comparison") {
      onRun({
        numeric_column: metric,
        segment_a: { [segColA]: segValA },
        segment_b: { [segColB]: segValB },
      });
    } else if (skill === "decompose") {
      onRun({
        metric_column: metricCol,
        date_column: dateCol,
        segment_column: segmentCol,
      });
    } else if (skill === "join_quality") {
      onRun({
        left_key: leftKey,
        right_key: rightKey,
        second_storage_path: secondPath ?? undefined,
      });
    }
  };

  const uploadSecond = async () => {
    if (!secondFile) return;
    setUploading(true);
    try {
      const supabase = createClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) throw new Error("Session expired");
      const uploadId = crypto.randomUUID();
      const safeName = secondFile.name.replace(/[^\w.\-]+/g, "_");
      const storagePath = `uploads/${user.id}/${uploadId.slice(0, 8)}-${safeName}`;
      const { error: upErr } = await supabase.storage
        .from("uploads")
        .upload(storagePath, secondFile, { upsert: false });
      if (upErr) throw new Error(upErr.message);
      setSecondPath(storagePath);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const select = (
    label: string,
    value: string,
    setter: (v: string) => void,
    options: string[],
    extra?: string
  ) => (
    <div className="space-y-1">
      <Label className="text-xs text-muted">{label}</Label>
      <select
        value={value}
        onChange={(e) => setter(e.target.value)}
        className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
      >
        <option value="">{extra ?? "Choose…"}</option>
        {options.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="space-y-3">
      {skill === "predictive_baseline" && select("Target column", target, setTarget, allCols)}
      {skill === "key_driver" && select("Outcome column", target, setTarget, allCols)}
      {skill === "psm" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {select("Treatment column (two values)", treatment, setTreatment, categoricalCols)}
          {select("Outcome column", outcome, setOutcome, numericCols)}
        </div>
      )}
      {skill === "what_if" && (
        <>
          {select("Baseline target", baselineTarget, setBaselineTarget, allCols)}
          <div className="space-y-2">
            {allCols.slice(0, 12).map((col) => (
              <div key={col} className="flex items-center gap-2">
                <Label className="w-40 shrink-0 truncate text-xs text-muted">{col}</Label>
                <Input
                  placeholder="value"
                  value={scenarioFields[col] ?? ""}
                  onChange={(e) => setScenarioFields((s) => ({ ...s, [col]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        </>
      )}
      {skill === "segment_comparison" && (
        <>
          {select("Metric column", metric, setMetric, numericCols)}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              {select("Segment A — column", segColA, setSegColA, categoricalCols)}
              <Input placeholder="Segment A value" value={segValA} onChange={(e) => setSegValA(e.target.value)} />
            </div>
            <div className="space-y-2">
              {select("Segment B — column", segColB, setSegColB, categoricalCols)}
              <Input placeholder="Segment B value" value={segValB} onChange={(e) => setSegValB(e.target.value)} />
            </div>
          </div>
        </>
      )}
      {skill === "decompose" && (
        <div className="grid gap-3 sm:grid-cols-3">
          {select("Metric column", metricCol, setMetricCol, numericCols)}
          {select("Date column", dateCol, setDateCol, dateCols, "Auto-detect first/last periods")}
          {select("Segment column", segmentCol, setSegmentCol, categoricalCols)}
        </div>
      )}
      {skill === "join_quality" && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {select("Report file key column", leftKey, setLeftKey, allCols)}
            {select("Second file key column", rightKey, setRightKey, allCols)}
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-muted">Second file</Label>
            <div className="flex items-center gap-2">
              <Input
                type="file"
                onChange={(e) => setSecondFile(e.target.files?.[0] ?? null)}
                className="flex-1"
              />
              {!secondPath && (
                <Button type="button" size="sm" variant="outline" onClick={uploadSecond} disabled={!secondFile || uploading}>
                  {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Upload"}
                </Button>
              )}
            </div>
            {secondPath && <p className="text-xs text-muted">Second file uploaded and ready.</p>}
          </div>
        </>
      )}

      <Button size="sm" onClick={handleRun} disabled={busy}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        Run
      </Button>
    </div>
  );
}
