import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Pro-gate card shown in place of Pro-only report tabs for Free plans. */
export function UpgradePrompt({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="card-panel flex flex-col items-center px-6 py-12 text-center">
      <Sparkles className="h-8 w-8 text-accent" />
      <h2 className="mt-4 text-xl font-medium">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted">{description}</p>
      <div className="mt-6 flex gap-3">
        <Button asChild size="sm">
          <Link href="/pricing">Upgrade to Pro</Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href="/dashboard/skills">See what&apos;s included</Link>
        </Button>
      </div>
    </div>
  );
}
