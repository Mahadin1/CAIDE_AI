import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";

export async function SiteNav() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur">
      <div className="container-page flex h-16 items-center justify-between">
        <Logo />
        <nav className="flex items-center gap-4">
          <Link
            href="/#how-it-works"
            className="hidden text-sm text-muted transition-colors hover:text-foreground sm:block"
          >
            How it works
          </Link>
          <Link
            href="/#pricing"
            className="hidden text-sm text-muted transition-colors hover:text-foreground sm:block"
          >
            Pricing
          </Link>
          {user ? (
            <Button asChild variant="secondary" size="sm">
              <Link href="/dashboard">Open dashboard</Link>
            </Button>
          ) : (
            <Button asChild size="sm">
              <Link href="/login">Get started</Link>
            </Button>
          )}
        </nav>
      </div>
    </header>
  );
}
