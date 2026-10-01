import { useState } from "react";
import { CircleAlert, RotateCcw, X } from "lucide-react";

import { retryRun } from "@/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useKbTitles } from "@/lib/useKbTitles";
import { FeedRow } from "./FeedRow";
import { PipelineStepper } from "./PipelineStepper";
import { fmtUsd } from "./LiveRunView";
import type { RunDetail } from "@/types";

const STAGE_NAME = {
  queued: "Queue",
  extracting: "Extract",
  indexing: "Index",
  judging: "Judge",
} as const;

export function FailedRunView({
  run,
  onChanged,
}: {
  run: RunDetail;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const titles = useKbTitles();
  const [retrying, setRetrying] = useState(false);
  const judged = run.findings.length;
  const total = run.summary.selected_total ?? 0;
  const pct = total > 0 ? Math.min(100, (judged / total) * 100) : 0;
  const stage = judged > 0 ? "Judge" : "Extract";

  async function retry() {
    setRetrying(true);
    try {
      await retryRun(run.summary.id);
      toast("Run re-queued", { message: "Analysis resumes where it left off." });
      onChanged();
    } catch (e) {
      toast("Retry failed", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setRetrying(false);
    }
  }

  return (
    <>
      <PipelineStepper status="failed" judged={judged} total={total} />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <span className="text-[13px] font-medium text-ink">
            Failed during {stage} — {judged} of {total} disclosures judged
          </span>
          <span className="text-[13px] text-muted-ink">
            aborted · {fmtUsd(run.summary.cost_usd)} spent
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Disclosures judged before failure"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct)}
          aria-valuetext={`${judged} of ${total} disclosures judged`}
          className="h-1.5 w-full overflow-hidden rounded-[3px] bg-soft-2"
        >
          <div className="h-full bg-danger" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div
        role="alert"
        className="flex flex-wrap items-start gap-4 rounded-3xl bg-surface p-4 shadow-[0_2px_4px_#0000000A]"
      >
        <CircleAlert className="mt-1 size-5 shrink-0 text-danger" aria-hidden />
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-sm font-medium text-danger">
            Run failed during {stage}
          </span>
          <span className="text-sm/[22px] text-muted-ink">
            {run.summary.error ??
              `The ${STAGE_NAME[run.summary.status as keyof typeof STAGE_NAME] ?? stage} step stopped unexpectedly. Partial findings were preserved — retry to continue from where it stopped.`}
          </span>
        </div>
        <Button
          variant="danger"
          size="sm"
          icon={<RotateCcw />}
          busy={retrying}
          onClick={() => void retry()}
        >
          Retry run
        </Button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-[15px] font-semibold text-ink">
          Findings before failure
        </h2>
        <span className="text-xs text-muted-ink">
          Run aborted · partial results preserved
        </span>
      </div>
      <div className="rounded-3xl bg-surface md:min-h-0 md:flex-1 md:overflow-y-auto">
        {[...run.findings].reverse().map((f) => (
          <div
            key={f.disclosure_id}
            className="border-b border-line last:border-0"
          >
            <FeedRow finding={f} title={titles.get(f.disclosure_id)} />
          </div>
        ))}
        <div className="flex h-[52px] items-center gap-3.5 px-4 text-muted-ink">
          <X className="size-5 text-danger" aria-hidden />
          <span className="text-[13px] font-medium">
            {run.summary.error
              ? "Run aborted"
              : "Aborted before the next disclosure"}
          </span>
        </div>
      </div>
    </>
  );
}
