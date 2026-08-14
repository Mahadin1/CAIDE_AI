"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS: { label: string; href: string; exact?: boolean }[] = [
  { label: "Overview", href: "", exact: true },
  { label: "Findings", href: "/findings" },
  { label: "Charts", href: "/charts" },
  { label: "Deep dive", href: "/deep-dive" },
  { label: "Skills", href: "/skills" },
  { label: "Q&A", href: "/qa" },
  { label: "Export", href: "/export" },
];

/** Persistent sub-navigation for a single report. Tabs are real routes so
 *  the back button and shareable URLs work. */
export function ReportSubNav({ reportId }: { reportId: string }) {
  const pathname = usePathname();
  const base = `/dashboard/reports/${reportId}`;

  return (
    <div className="flex gap-1 overflow-x-auto rounded-md border border-border bg-surface p-1">
      {TABS.map((tab) => {
        const href = `${base}${tab.href}`;
        const active = tab.exact ? pathname === href : pathname === href;
        return (
          <Link
            key={tab.label}
            href={href}
            className={cn(
              "whitespace-nowrap rounded px-3 py-1.5 text-sm transition-colors",
              active
                ? "bg-elevated font-medium text-foreground"
                : "text-muted hover:text-foreground"
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
