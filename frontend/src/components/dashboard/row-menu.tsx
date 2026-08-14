"use client";

import { useEffect, useRef, useState } from "react";
import { MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";

export interface RowMenuItem {
  label: string;
  icon?: React.ReactNode;
  href?: string;
  onClick?: () => void;
  danger?: boolean;
  download?: boolean;
}

/**
 * A small kebab/dots dropdown used on dashboard rows. Closes on outside
 * click and on Escape; no external menu dependency.
 */
export function RowMenu({
  items,
  ariaLabel = "More options",
}: {
  items: RowMenuItem[];
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-md p-1.5 text-muted transition-colors hover:bg-border hover:text-foreground"
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 min-w-44 overflow-hidden rounded-md border border-border bg-elevated p-1 shadow-xl"
        >
          {items.map((item, i) =>
            item.href ? (
              <a
                key={i}
                role="menuitem"
                href={item.href}
                download={item.download}
                onClick={() => setOpen(false)}
                className={cn(
                  "flex items-center gap-2 rounded px-2.5 py-1.5 text-sm transition-colors",
                  item.danger
                    ? "text-[var(--danger-fg)] hover:bg-[var(--danger-border)]"
                    : "text-foreground hover:bg-border"
                )}
              >
                {item.icon}
                {item.label}
              </a>
            ) : (
              <button
                key={i}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  item.onClick?.();
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm transition-colors",
                  item.danger
                    ? "text-[var(--danger-fg)] hover:bg-[var(--danger-border)]"
                    : "text-foreground hover:bg-border"
                )}
              >
                {item.icon}
                {item.label}
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
