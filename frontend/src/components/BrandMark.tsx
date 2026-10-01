import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The Accordance mark — a blue app tile whose "disclosure lines" resolve into
 * a check. Same artwork as /favicon.svg, inlined so it can be sized inline
 * without a network fetch.
 */
export function BrandMark({ className }: { className?: string }) {
  // useId emits ":r0:"-style ids — colons break url(#…) refs in some engines.
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
          <stop offset="0" stopColor="#3BA4FF" />
          <stop offset="1" stopColor="#0370DC" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill={`url(#${gid})`} />
      <rect x="9" y="7.5" width="14" height="2.8" rx="1.4" fill="#fff" />
      <rect
        x="9"
        y="12.5"
        width="9"
        height="2.8"
        rx="1.4"
        fill="#fff"
        opacity="0.9"
      />
      <path
        d="M9.5 20 L14 24.5 L23 15.5"
        fill="none"
        stroke="#fff"
        strokeWidth="3.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
