import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent text-[#000000]",
        secondary: "border-transparent bg-[#111111] text-foreground",
        outline: "text-muted",
        success: "border-transparent bg-[#16351f] text-[#4ade80]",
        warning: "border-transparent bg-[#3a2f16] text-[#facc15]",
        danger: "border-transparent bg-[#3a1a1a] text-[#f87171]",
        info: "border-transparent bg-[#1a1a1a] text-[#fafafa]",
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
