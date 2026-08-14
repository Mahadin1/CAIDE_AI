"use client";

import { useCallback, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { openCheckout, type BillingPlan } from "@/lib/paddle";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { Plan } from "@/lib/types";

const TIERS: {
  id: BillingPlan;
  name: string;
  price: number;
  credits: number;
  blurb: string;
  features: string[];
}[] = [
  {
    id: "starter",
    name: "Starter",
    price: 5,
    credits: 30,
    blurb: "For occasional analyses",
    features: [
      "30 analyses per month",
      "Full EDA report + charts",
      "Segmentation, forecasting & group tests",
      "PDF & CSV exports",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    price: 15,
    credits: 100,
    blurb: "For regular data work",
    features: [
      "100 analyses per month",
      "Everything in Starter",
      "Advanced skills (baseline, PSM, what-if…) charged per run",
      "300 live Q&A credits",
      "Priority processing",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    price: 30,
    credits: 300,
    blurb: "For teams and heavy use",
    features: [
      "300 analyses per month",
      "Everything in Pro",
      "1,000 live Q&A credits",
      "Best value per analysis",
    ],
  },
];

export function PlanPicker({ currentPlan }: { currentPlan: Plan }) {
  const [checking, setChecking] = useState<BillingPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const choose = useCallback(async (plan: BillingPlan) => {
    setChecking(plan);
    setError(null);
    try {
      const { createClient } = await import("@/lib/supabase/client");
      const client = createClient();
      const {
        data: { user },
      } = await client.auth.getUser();
      if (!user) {
        setError("You need to be signed in to change your plan.");
        return;
      }
      const opened = await openCheckout(plan, user.id);
      if (!opened) {
        setError(
          "Billing isn't connected yet — please contact support to change your plan."
        );
      }
    } finally {
      setChecking(null);
    }
  }, []);

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-[var(--danger-fg)]">{error}</p>}
      <div className="grid gap-4 md:grid-cols-3">
        {TIERS.map((tier) => {
          const active = currentPlan === tier.id;
          return (
            <div
              key={tier.id}
              className={
                active
                  ? "flex flex-col rounded-lg border border-accent bg-elevated p-5"
                  : "card-panel flex flex-col p-5"
              }
            >
              <div className="flex items-center justify-between">
                <h3 className="font-medium">{tier.name}</h3>
                {active && <Badge>Current</Badge>}
              </div>
              <p className="mt-0.5 text-xs text-muted">{tier.blurb}</p>
              <p className="mt-4 font-heading text-3xl font-medium">
                ${tier.price}
                <span className="text-base text-muted">/mo</span>
              </p>
              <p className="mt-1 text-xs text-muted">
                {tier.credits} analyses per month
              </p>
              <ul className="mt-4 flex-1 space-y-2 text-sm">
                {tier.features.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Button
                className="mt-5 w-full"
                variant={active ? "outline" : "default"}
                size="sm"
                disabled={active || checking !== null}
                onClick={() => choose(tier.id)}
              >
                {checking === tier.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : active ? (
                  "Current plan"
                ) : (
                  `Switch to ${tier.name}`
                )}
              </Button>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-muted">
        Changing plans applies the new monthly credit allowance immediately.
        You can downgrade or cancel any time.
      </p>
    </div>
  );
}
