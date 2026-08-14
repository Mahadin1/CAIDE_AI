"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Search } from "lucide-react";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserMenu } from "@/components/dashboard/user-menu";

const TAB_LABEL: Record<string, string> = {
  findings: "Findings",
  charts: "Charts",
  "deep-dive": "Deep dive",
  skills: "Skills",
  qa: "Q&A",
  export: "Export",
};

interface Crumb {
  label: string;
  href?: string;
}

function crumbsFromPath(pathname: string): Crumb[] {
  const parts = pathname.split("/").filter(Boolean);

  if (parts.length === 2) {
    const label =
      parts[1] === "files"
        ? "Files"
        : parts[1] === "reports"
          ? "Reports"
          : parts[1] === "skills"
            ? "Skills"
            : parts[1] === "account"
              ? "Account"
              : parts[1].charAt(0).toUpperCase() + parts[1].slice(1);
    return [{ label }];
  }

  if (parts[1] === "files" && parts.length === 3) {
    return [{ label: "Files", href: "/dashboard/files" }, { label: "File" }];
  }

  if (parts[1] === "account" && parts.length === 3) {
    return [{ label: "Account", href: "/dashboard/account" }, { label: "Billing" }];
  }

  if (parts[1] === "reports" && parts.length === 3) {
    return [{ label: "Reports", href: "/dashboard/reports" }, { label: "Report" }];
  }

  if (parts[1] === "reports" && parts.length === 4) {
    const tab = TAB_LABEL[parts[3]] ?? parts[3].charAt(0).toUpperCase() + parts[3].slice(1);
    return [
      { label: "Reports", href: "/dashboard/reports" },
      { label: "Report", href: `/dashboard/reports/${parts[2]}` },
      { label: tab },
    ];
  }

  const label = parts[1]
    ? parts[1].charAt(0).toUpperCase() + parts[1].slice(1)
    : "Overview";
  return [{ label }];
}

export function DashboardHeader({
  name,
  email,
  signOut,
}: {
  name: string | null;
  email: string | undefined;
  signOut: () => Promise<void>;
}) {
  const pathname = usePathname();
  const crumbs = crumbsFromPath(pathname);

  return (
    <header className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-border bg-background/90 px-4 backdrop-blur md:px-8">
      <SidebarTrigger className="md:hidden" />
      <Breadcrumb className="hidden sm:block">
        <BreadcrumbList>
          {crumbs.map((crumb, i) => {
            const last = i === crumbs.length - 1;
            return (
              <React.Fragment key={i}>
                <BreadcrumbItem>
                  {last ? (
                    <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink href={crumb.href ?? "#"}>
                      {crumb.label}
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
                {!last && <BreadcrumbSeparator />}
              </React.Fragment>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>

      <div className="ml-auto flex items-center gap-1.5">
        <CommandTriggerButton />
        <ThemeToggle />
        <UserMenu name={name} email={email} signOut={signOut} />
      </div>
    </header>
  );
}

function CommandTriggerButton() {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="hidden gap-2 text-muted md:flex"
      onClick={() => window.dispatchEvent(new CustomEvent("datascope:open-palette"))}
      aria-label="Open command palette"
    >
      <Search className="h-4 w-4" />
      <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-0.5 rounded border border-border bg-elevated px-1.5 font-mono text-[10px] font-medium text-muted">
        ⌘K
      </kbd>
    </Button>
  );
}
