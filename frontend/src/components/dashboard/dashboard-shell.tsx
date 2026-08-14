"use client";

import {
  Sidebar,
  SidebarInset,
  SidebarProvider,
} from "@/components/ui/sidebar";
import { DashboardSidebar } from "@/components/dashboard/dashboard-sidebar";
import { DashboardHeader } from "@/components/dashboard/dashboard-header";
import { CommandPalette } from "@/components/dashboard/command-palette";
import type { ReportListItem } from "@/lib/queries";
import type { Profile, Upload } from "@/lib/types";

export function DashboardShell({
  profile,
  uploads,
  reports,
  signOut,
  children,
}: {
  profile: Profile;
  uploads: Upload[];
  reports: ReportListItem[];
  signOut: () => Promise<void>;
  children: React.ReactNode;
}) {
  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <DashboardSidebar profile={profile} />
      </Sidebar>
      <SidebarInset>
        <DashboardHeader
          name={profile.name}
          email={profile.email ?? undefined}
          signOut={signOut}
        />
        <div className="flex-1 px-4 py-8 md:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </div>
      </SidebarInset>
      <CommandPalette uploads={uploads} reports={reports} />
    </SidebarProvider>
  );
}
