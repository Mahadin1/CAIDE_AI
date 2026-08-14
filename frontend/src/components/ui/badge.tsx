import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent text-accent-foreground",
        secondary: "border-transparent bg-elevated text-foreground",
        outline: "text-muted",
        success: "border-transparent bg-[var(--success-bg)] text-[var(--success-fg)]",
        warning: "border-transparent bg-[var(--warning-bg)] text-[var(--warning-fg)]",
        danger: "border-transparent bg-[var(--danger-bg)] text-[var(--danger-fg)]",
        info: "border-transparent bg-accent/15 text-accent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
