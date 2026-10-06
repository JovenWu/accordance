import * as React from "react";

import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  children,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col gap-1 rounded-3xl bg-surface p-4 shadow-card",
        className,
      )}
    >
      <span className="text-xs text-muted-ink">{label}</span>
      <span className="text-[22px] font-semibold leading-7 text-ink">
        {value}
      </span>
      {hint && <span className="text-xs text-muted-ink">{hint}</span>}
      {children}
    </div>
  );
}
