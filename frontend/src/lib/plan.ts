import type { Plan } from "@/lib/types";

export const PLAN_LABEL: Record<Plan, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  scale: "Scale",
};

export const PLAN_CREDITS: Record<Plan, number> = {
  free: 3,
  starter: 30,
  pro: 100,
  scale: 300,
};

export function planLabel(plan: Plan): string {
  return PLAN_LABEL[plan] ?? "Free";
}
