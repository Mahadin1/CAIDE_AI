"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BarChart3,
  CreditCard,
  FileBarChart,
  Files,
  FolderOpen,
  LayoutDashboard,
  Sparkles,
  UploadCloud,
  User,
  Wand2,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import type { ReportListItem } from "@/lib/queries";
import type { Upload } from "@/lib/types";

export function CommandPalette({
  uploads,
  reports,
}: {
  uploads: Upload[];
  reports: ReportListItem[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpen = () => setOpen(true);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("datascope:open-palette", onOpen);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("datascope:open-palette", onOpen);
    };
  }, []);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const files = uploads.filter((u) => u.status === "ready");

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search files, reports and actions…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigate">
          <CommandItem onSelect={() => go("/dashboard")}>
            <LayoutDashboard />
            Overview
          </CommandItem>
          <CommandItem onSelect={() => go("/dashboard/files")}>
            <Files />
            Files
          </CommandItem>
          <CommandItem onSelect={() => go("/dashboard/reports")}>
            <BarChart3 />
            Reports
          </CommandItem>
          <CommandItem onSelect={() => go("/dashboard/skills")}>
            <Wand2 />
            Skills
          </CommandItem>
          <CommandItem onSelect={() => go("/dashboard/account")}>
            <User />
            Account
          </CommandItem>
          <CommandItem onSelect={() => go("/dashboard/account/billing")}>
            <CreditCard />
            Billing &amp; plan
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Actions">
          <CommandItem onSelect={() => go("/dashboard/files#upload")}>
            <UploadCloud />
            Upload a file
            <CommandShortcut>⌘U</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        {files.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Files">
              {files.slice(0, 8).map((f) => (
                <CommandItem
                  key={f.id}
                  onSelect={() => go(`/dashboard/files/${f.id}`)}
                >
                  <FolderOpen />
                  {f.filename}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {reports.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Reports">
              {reports.slice(0, 8).map((r) => (
                <CommandItem
                  key={r.id}
                  onSelect={() => go(`/dashboard/reports/${r.id}`)}
                >
                  <FileBarChart />
                  {r.uploads?.filename ?? "Report"}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        <CommandSeparator />

        <CommandGroup heading="Resources">
          <CommandItem onSelect={() => go("/features")}>
            <Sparkles />
            Features
          </CommandItem>
          <CommandItem onSelect={() => go("/pricing")}>
            <BarChart3 />
            Pricing
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
