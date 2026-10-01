import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import type { DisclosureStatus, RunStatus } from "@/types";

const chipVariants = cva(
  "inline-flex w-fit items-center gap-0.5 rounded-2xl font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        accent: "bg-accent-soft text-accent",
        success: "bg-success-soft text-success",
        warning: "bg-warning-soft text-warning",
        danger: "bg-danger-soft text-danger",
        neutral: "bg-soft text-ink",
      },
      size: {
        sm: "px-2 py-0.5 text-xs",
        lg: "px-3 py-1 text-sm",
      },
    },
    defaultVariants: { tone: "neutral", size: "sm" },
  },
);

export interface ChipProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {}

export function Chip({ className, tone, size, ...props }: ChipProps) {
  return (
    <span className={cn(chipVariants({ tone, size }), className)} {...props} />
  );
}

const RUN_STATUS: Record<RunStatus, { label: string; tone: ChipProps["tone"] }> =
  {
    queued: { label: "Queued", tone: "neutral" },
    extracting: { label: "Extracting", tone: "accent" },
    indexing: { label: "Indexing", tone: "accent" },
    judging: { label: "Judging", tone: "warning" },
    completed: { label: "Completed", tone: "success" },
    failed: { label: "Failed", tone: "danger" },
    cancelled: { label: "Cancelled", tone: "neutral" },
  };

export function RunStatusChip({
  status,
  size,
  className,
}: {
  status: RunStatus;
  size?: ChipProps["size"];
  className?: string;
}) {
  const s = RUN_STATUS[status];
  return (
    <Chip tone={s.tone} size={size} className={className}>
      {s.label}
    </Chip>
  );
}

const FINDING_STATUS: Record<
  DisclosureStatus,
  { label: string; tone: ChipProps["tone"] }
> = {
  covered: { label: "Covered", tone: "success" },
  partial: { label: "Partial", tone: "warning" },
  missing: { label: "Missing", tone: "danger" },
  error: { label: "Error", tone: "danger" },
};

export function DisclosureStatusChip({
  status,
  na,
  className,
}: {
  status: DisclosureStatus;
  /** Score-0 N/A findings render as a neutral N/A chip instead of Covered. */
  na?: boolean;
  className?: string;
}) {
  if (na) {
    return <Chip className={className}>N/A</Chip>;
  }
  const s = FINDING_STATUS[status];
  return (
    <Chip tone={s.tone} className={className}>
      {s.label}
    </Chip>
  );
}

/** Per-score pill color ramp: green (5) → red (1), gray for 0/error. */
const SCORE_TONE: Record<number, string> = {
  5: "bg-success-soft text-success",
  4: "bg-lime-soft text-lime",
  3: "bg-warning-soft text-warning",
  2: "bg-orange-soft text-orange",
  1: "bg-danger-soft text-danger",
  0: "bg-soft text-muted-ink",
};

/** Solid rounded score pill used in findings/diff rows. */
export function ScorePill({
  score,
  className,
}: {
  score: number | null;
  className?: string;
}) {
  const tone =
    score == null
      ? "bg-soft text-muted-ink"
      : (SCORE_TONE[score] ?? "bg-soft text-muted-ink");
  return (
    <span
      className={cn(
        "relative inline-flex w-fit items-center rounded-full px-2.5 py-1 text-[13px] font-semibold tabular-nums",
        tone,
        className,
      )}
    >
      <span aria-hidden>{score == null ? "!" : score}</span>
      <span className="sr-only">
        {score == null ? "No score" : `Score ${score} of 5`}
      </span>
    </span>
  );
}
