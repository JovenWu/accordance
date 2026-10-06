import { useId } from "react";

import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  const gid = `bm-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn("shrink-0", className)}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FFC400" />
          <stop offset="1" stopColor="#F59E0B" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill={`url(#${gid})`} />
      <rect x="9" y="7.5" width="14" height="2.8" rx="1.4" fill="#101114" />
      <rect
        x="9"
        y="12.5"
        width="9"
        height="2.8"
        rx="1.4"
        fill="#101114"
        opacity="0.9"
      />
      <path
        d="M9.5 20 L14 24.5 L23 15.5"
        fill="none"
        stroke="#101114"
        strokeWidth="3.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
