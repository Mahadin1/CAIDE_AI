"use client";

import { useEffect, useState } from "react";
import { timeAgo } from "@/lib/utils";

/**
 * A relative timestamp ("3m ago") that refreshes on a timer. The server and
 * client render slightly different values because `timeAgo` depends on
 * `Date.now()`, so the element opts out of hydration matching and corrects
 * itself immediately after mount — this is what prevents the React
 * "Hydration failed" error on the dashboard.
 */
export function RelativeTime({
  date,
  className,
}: {
  date: string | null | undefined;
  className?: string;
}) {
  const [label, setLabel] = useState(() => timeAgo(date));

  useEffect(() => {
    setLabel(timeAgo(date));
    const timer = setInterval(() => setLabel(timeAgo(date)), 30_000);
    return () => clearInterval(timer);
  }, [date]);

  return (
    <span className={className} suppressHydrationWarning>
      {label}
    </span>
  );
}
