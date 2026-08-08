"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { openCheckout, isPaddleConfigured, type BillingPlan } from "@/lib/paddle";
import { Button } from "@/components/ui/button";
import { Check } from "lucide-react";

const TIERS: {
  id: BillingPlan | "free";
  name: string;
  price: number | null;
  blurb: string;
  features: string[];
  accent?: boolean;
}[] = [
  {
    id: "free",
    name: "Free",
    price: 0,
    blurb: "For trying things out",
    features: [
      "3 analyses per month",
      "Full EDA summary (stats + narrative)",
      "Interactive charts",
      "7-day report history",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    price: 15,
    blurb: "For regular data work",
    accent: true,
    features: [
      "100 analyses per month",
      "PDF export of every report",
      "Everything in Free",
      "Priority processing",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    price: 30,
    blurb: "For teams and heavy use",
    features: [
      "300 analyses per month",
      "Everything in Pro",
      "Best value per analysis",
      "Priority processing",
    ],
  },
];

export function PricingSection() {
  const [userId, setUserId] = useState<string | null>(null);
  const [checking, setChecking] = useState<BillingPlan | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setUserId(data.user?.id ?? null);
    });
  }, []);

  const onUpgrade = useCallback(
    async (plan: BillingPlan) => {
      if (!userId) {
        window.location.href = "/login?next=/dashboard";
        return;
      }
      setChecking(plan);
      try {
        const opened = await openCheckout(plan, userId);
        if (!opened) {
          window.location.href = "/dashboard?billing=unavailable";
        }
      } finally {
        setChecking(null);
      }
    },
    [userId]
  );

  return (
    <section id="pricing" className="section-padding border-t border-border">
      <div className="container-page">
        <p className="text-sm font-medium uppercase tracking-widest text-muted">
          Pricing
        </p>
        <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
          Start free. Upgrade when the analysis matters.
        </h2>

        <div className="mx-auto mt-14 grid max-w-4xl gap-6 md:grid-cols-3">
          {TIERS.map((tier) => (
            <div
              key={tier.id}
              className={
                tier.accent
                  ? "flex flex-col rounded-lg border border-accent bg-surface p-6"
                  : "card-panel flex flex-col p-6"
              }
            >
              <h3 className="text-lg font-medium">{tier.name}</h3>
              <p className="mt-1 text-sm text-muted">{tier.blurb}</p>
              <p className="mt-6 font-heading text-4xl font-medium">
                {tier.price === 0 ? "$0" : `$${tier.price}`}
                <span className="text-lg text-muted">/mo</span>
              </p>
              <p className="mt-1 text-sm text-muted">
                {tier.id === "free"
                  ? "forever"
                  : "billed monthly, cancel anytime"}
              </p>
              <ul className="mt-6 flex-1 space-y-3 text-sm">
                {tier.features.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              {tier.id === "free" ? (
                <Button asChild variant="outline" className="mt-8 w-full">
                  <Link href="/login">Start with Free</Link>
                </Button>
              ) : (
                <Button
                  onClick={() => onUpgrade(tier.id as BillingPlan)}
                  disabled={checking !== null}
                  className="mt-8 w-full"
                >
                  {checking === tier.id
                    ? "Opening checkout…"
                    : `Upgrade to ${tier.name}`}
                </Button>
              )}
            </div>
          ))}
        </div>
        {!isPaddleConfigured() && (
          <p className="mt-6 text-center text-xs text-muted">
            Billing not connected yet — contact sales@datascope.app
          </p>
        )}
      </div>
    </section>
  );
}
