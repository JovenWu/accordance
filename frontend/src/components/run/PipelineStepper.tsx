import { Check, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RunStatus } from "@/types";

const STEPS = ["Extract", "Index", "Judge", "Finalize"] as const;

type StepState = "done" | "active" | "failed" | "pending";

const STATUS_TO_INDEX: Record<RunStatus, number> = {
  queued: 0,
  extracting: 0,
  indexing: 1,
  judging: 2,
  completed: 4,
  failed: -1,
  cancelled: -1,
};

export function PipelineStepper({
  status,
  judged,
  total,
}: {
  status: RunStatus;
  judged: number;
  total: number;
}) {
  let activeIdx = STATUS_TO_INDEX[status];
  let failedIdx = -1;
  if (status === "failed" || status === "cancelled") {
    activeIdx = judged > 0 ? 2 : 0;
    failedIdx = activeIdx;
  }

  const states: StepState[] = STEPS.map((_, i) => {
    if (i === failedIdx) return "failed";
    if (i < activeIdx) return "done";
    if (i === activeIdx && status !== "completed") return "active";
    if (status === "completed") return "done";
    return "pending";
  });

  return (
    <div className="w-full overflow-x-auto rounded-3xl bg-surface">
      <div
        role="list"
        aria-label="Pipeline progress"
        className="flex w-full items-stretch px-3 py-4 sm:min-w-[560px] sm:items-center sm:px-6 sm:py-5"
      >
      {STEPS.map((name, i) => {
        const st = states[i];
        const meta = stepMeta(name, st, { status, judged, total });
        return (
          <div
            key={name}
            role="listitem"
            aria-current={st === "active" ? "step" : undefined}
            className="contents"
          >
            {i > 0 && (
              <div
                aria-hidden
                className={cn(
                  "mt-[13px] h-[2px] min-w-2 flex-1 self-start transition-colors duration-500 sm:mt-0 sm:self-center",
                  states[i - 1] === "done" ? "bg-success" : "bg-soft-2",
                )}
              />
            )}
            <div className="flex flex-col items-center gap-1.5 sm:flex-row sm:gap-2.5">
              <span
                className={cn(
                  "grid size-7 shrink-0 place-items-center rounded-full transition-colors duration-300 [&_svg]:size-4",
                  st === "done" && "bg-success text-white",
                  st === "active" && "bg-accent text-accent-ink",
                  st === "failed" && "bg-danger text-white",
                  st === "pending" && "bg-soft-2 text-muted-ink",
                )}
              >
                {st === "done" && <Check aria-hidden />}
                {st === "active" && (
                  <Loader2 className="animate-spin" aria-hidden />
                )}
                {st === "failed" && <X aria-hidden />}
                {st === "pending" && (
                  <span className="text-xs font-semibold">{i + 1}</span>
                )}
              </span>
              <span className="flex flex-col items-center gap-px text-center sm:items-start sm:text-left">
                <span
                  className={cn(
                    "text-[11px] font-medium sm:text-[13px]",
                    st === "pending" ? "text-muted-ink" : "text-ink",
                  )}
                >
                  {name}
                </span>
                <span className="hidden text-[11px] text-muted-ink sm:block">
                  {meta}
                </span>
              </span>
            </div>
          </div>
        );
      })}
      </div>
    </div>
  );
}

function stepMeta(
  name: string,
  st: StepState,
  ctx: { status: RunStatus; judged: number; total: number },
): string {
  if (name === "Judge" && (st === "active" || st === "failed")) {
    const pct = ctx.total > 0 ? Math.round((ctx.judged / ctx.total) * 100) : 0;
    return `${ctx.judged} of ${ctx.total} · ${pct}%`;
  }
  if (st === "done") return "done";
  if (st === "active") {
    if (name === "Extract")
      return ctx.status === "queued" ? "waiting for a worker" : "parsing pages";
    if (name === "Index") return "embedding chunks";
    return "judging disclosures";
  }
  if (st === "failed") return "failed";
  return "pending";
}
