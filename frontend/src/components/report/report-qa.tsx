"use client";
import { useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { QaTurn } from "@/lib/types";

/** Report Q&A (#8) — Pro+ only, metered against the separate qa_credits meter.
 *  Answers come only from the stored report digest; the LLM never sees raw rows. */
export function ReportQa({
  reportId,
  qaCredits,
}: {
  reportId: string;
  qaCredits: number;
}) {
  const [turns, setTurns] = useState<QaTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [credits, setCredits] = useState(qaCredits);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refresh = () => {
    fetch(`/api/reports/${reportId}/qa`)
      .then((res) => res.json())
      .then((body) => setTurns(body.turns ?? []))
      .catch(() => {});
  };
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    const optimistic: QaTurn = {
      id: `local-${Date.now()}`,
      report_id: reportId,
      question: q,
      answer: "",
      answered: false,
      model: null,
      created_at: new Date().toISOString(),
    };
    setTurns((t) => [...t, optimistic]);
    setQuestion("");
    try {
      const res = await fetch(`/api/reports/${reportId}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? "Could not answer that question");
      }
      setTurns((t) => t.map((x) => (x.id === optimistic.id ? { ...x, answer: body.answer, answered: true } : x)));
      setCredits((c) => Math.max(0, c - 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Q&A failed");
      setTurns((t) => t.filter((x) => x.id !== optimistic.id));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ask about this report</CardTitle>
        <CardDescription>
          Live Q&amp;A answered only from this report&apos;s analysis — no raw rows leave
          the dataset. You have <strong>{credits}</strong> Q&amp;A credit
          {credits === 1 ? "" : "s"} this month.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {turns.length === 0 && !busy ? (
          <p className="mb-4 text-sm text-muted">
            Examples: “Which columns are most associated with churn?”, “How confident is
            the forecast?”, “Why are these findings ranked medium severity?”
          </p>
        ) : (
          <div className="mb-4 max-h-96 space-y-3 overflow-y-auto pr-1">
            {turns.map((t) => (
              <div key={t.id} className="space-y-1">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-md rounded-br-sm border border-border bg-elevated px-3 py-2 text-sm">
                    {t.question}
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[90%] whitespace-pre-wrap rounded-md rounded-bl-sm border border-border bg-surface px-3 py-2 text-sm text-muted">
                    {t.answered ? t.answer : <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  </div>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        {error && (
          <div className="mb-3 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3">
            <p className="text-sm text-[var(--danger-fg)]">{error}</p>
          </div>
        )}

        <div className="flex gap-2">
          <Input
            placeholder="Ask a question about this report…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask();
              }
            }}
            disabled={busy}
          />
          <Button size="icon" onClick={() => void ask()} disabled={busy || !question.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
