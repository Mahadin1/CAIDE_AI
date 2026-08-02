import Link from "next/link";

import { Button } from "@/components/ui/button";

export function FinalCta() {
  return (
    <section className="section-padding border-t border-[#232a33]">
      <div className="container-page">
        <div className="card-panel flex flex-col items-center px-6 py-16 text-center md:py-20">
          <h2 className="max-w-2xl text-3xl font-medium md:text-4xl">
            Your next dataset has a story. Let us read it.
          </h2>
          <p className="mt-4 max-w-xl text-muted">
            Free accounts get two full analyses every month. No credit card, no
            spreadsheet gymnastics.
          </p>
          <div className="mt-8">
            <Button asChild size="lg">
              <Link href="/login">Analyze your first file free</Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
