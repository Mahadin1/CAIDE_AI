import Link from "next/link";

import { Button } from "@/components/ui/button";

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2">
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-[#000000]">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          className="h-4 w-4"
          aria-hidden="true"
        >
          <path
            d="M4 17l5-5 3 3 8-9"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="20" cy="6" r="1.6" fill="currentColor" />
        </svg>
      </span>
      <span className="font-heading text-lg font-medium text-foreground">
        DataScope
      </span>
    </Link>
  );
}
