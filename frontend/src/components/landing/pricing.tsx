"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { openProCheckout, isPaddleConfigured } from "@/lib/paddle";
import { Button } from "@/components/ui/button";
import { Check } from "lucide-react";

const freeFeatures = [
  "2 reports per month",
  "Full EDA summary (stats + narrative)",
  "Interactive charts",
  "7-day report history",
];

const proFeatures = [
  "Unlimited reports",
  "PDF export of every report",
  "Everything in Free",
  "Priority processing",
];

export function PricingSection() {
  const [userId, setUserId] = useState<string | null>(null);
  const [checkingOut, setCheckingOut] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setUserId(data.user?.id ?? null);
    });
  }, []);

  const onUpgrade = useCallback(async () => {
    if (!userId) {
      window.location.href = "/login?next=/dashboard";
      return;
    }
    setCheckingOut(true);
    try {
      const opened = await openProCheckout(userId);
      if (!opened) {
        window.location.href = "/dashboard?billing=unavailable";
      }
    } finally {
      setCheckingOut(false);
    }
  }, [userId]);

  return (
    <section id="pricing" className="section-padding border-t border-[#1f1f1f]">
      <div className="container-page">
        <p className="text-sm font-medium uppercase tracking-widest text-muted">
          Pricing
        </p>
        <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
          Start free. Upgrade when the analysis matters.
        </h2>

        <div className="mx-auto mt-14 grid max-w-3xl gap-6 md:grid-cols-2">
          {/* Free */}
          <div className="card-panel flex flex-col p-6">
            <h3 className="text-lg font-medium">Free</h3>
            <p className="mt-1 text-sm text-muted">For trying things out</p>
            <p className="mt-6 font-heading text-4xl font-medium">$0</p>
            <p className="mt-1 text-sm text-muted">forever</p>
            <ul className="mt-6 flex-1 space-y-3 text-sm">
              {freeFeatures.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-[#fafafa]" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <Button asChild variant="outline" className="mt-8 w-full">
              <Link href="/login">Start with Free</Link>
            </Button>
          </div>

          {/* Pro — accent border, upgrade triggers Paddle checkout */}
          <div className="flex flex-col rounded-lg border border-[#fafafa] bg-[#0a0a0a] p-6">
            <h3 className="text-lg font-medium">Pro</h3>
            <p className="mt-1 text-sm text-muted">For teams and daily use</p>
            <p className="mt-6 font-heading text-4xl font-medium">
              $12<span className="text-lg text-muted">/mo</span>
            </p>
            <p className="mt-1 text-sm text-muted">billed monthly, cancel anytime</p>
            <ul className="mt-6 flex-1 space-y-3 text-sm">
              {proFeatures.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-[#fafafa]" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <Button
              onClick={onUpgrade}
              disabled={checkingOut}
              className="mt-8 w-full"
            >
              {checkingOut ? "Opening checkout…" : "Upgrade to Pro"}
            </Button>
            {!isPaddleConfigured() && (
              <p className="mt-3 text-center text-xs text-muted">
                Billing not connected yet — contact sales@datascope.app
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
