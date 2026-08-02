import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent text-[#0b0e11]",
        secondary: "border-transparent bg-[#1b2230] text-foreground",
        outline: "text-muted",
        success: "border-transparent bg-[#16351f] text-[#4ade80]",
        warning: "border-transparent bg-[#3a2f16] text-[#facc15]",
        danger: "border-transparent bg-[#3a1a1a] text-[#f87171]",
        info: "border-transparent bg-[#0f2b36] text-[#00d4ff]",
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
