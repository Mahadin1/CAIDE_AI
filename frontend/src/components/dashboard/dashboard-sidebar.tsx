"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, CreditCard, Files, LayoutDashboard, Plus, Wand2 } from "lucide-react";
import { Logo } from "@/components/logo";
import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { planLabel } from "@/lib/plan";
import type { Profile } from "@/lib/types";

const NAV = [
  {
    href: "/dashboard",
    label: "Overview",
    icon: LayoutDashboard,
    exact: true,
  },
  { href: "/dashboard/files", label: "Files", icon: Files },
  { href: "/dashboard/reports", label: "Reports", icon: BarChart3 },
  { href: "/dashboard/skills", label: "Skills", icon: Wand2 },
];

export function DashboardSidebar({ profile }: { profile: Profile }) {
  const pathname = usePathname();
  const { state } = useSidebar();
  const collapsed = state === "collapsed";

  const isActive = (item: (typeof NAV)[number]) =>
    item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(item.href + "/");

  return (
    <>
      <SidebarHeader>
        <div className={cn("flex items-center gap-2", collapsed && "justify-center")}>
          <Logo />
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item)}
                    tooltip={collapsed ? item.label : undefined}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild variant="outline" tooltip={collapsed ? "Start an analysis" : undefined}>
                  <Link href="/dashboard/files#upload">
                    <Plus />
                    <span>Start analysis</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarSeparator />

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={pathname === "/dashboard/account/billing"}
              tooltip={collapsed ? "Billing &amp; plan" : undefined}
            >
              <Link href="/dashboard/account/billing">
                <CreditCard />
                <span className="flex w-full flex-col gap-0.5">
                  <span className="flex items-center gap-2">
                    <span className="truncate">{planLabel(profile.plan)} plan</span>
                    <Badge variant={profile.plan === "free" ? "secondary" : "info"}>
                      {profile.credits} credits
                    </Badge>
                  </span>
                  <span className="text-xs text-muted">
                    {profile.plan === "free"
                      ? "Upgrade for more"
                      : `${profile.qa_credits} Q&amp;A this month`}
                  </span>
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </>
  );
}
