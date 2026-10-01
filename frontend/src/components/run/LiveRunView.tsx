import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { useKbTitles } from "@/lib/useKbTitles";
import { FeedRow } from "./FeedRow";
import { PipelineStepper } from "./PipelineStepper";
import type { RunDetail, RunStatus } from "@/types";

const STAGE_LABEL: Partial<Record<RunStatus, string>> = {
  queued: "Queued — waiting for a worker",
  extracting: "Extracting PDF text",
  indexing: "Indexing evidence chunks",
  judging: "Judging disclosures",
};

export function LiveRunView({ run }: { run: RunDetail; onChanged: () => void }) {
  const titles = useKbTitles();
  const judged = run.findings.length;
  const total = run.summary.selected_total ?? 0;
  const pct = total > 0 ? Math.min(100, (judged / total) * 100) : 0;

  return (
    <>
      <PipelineStepper
        status={run.summary.status}
        judged={judged}
        total={total}
      />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <span className="text-[13px] font-medium text-ink">
            {STAGE_LABEL[run.summary.status] ?? "Working"}
          </span>
          <span className="text-[13px] text-muted-ink">
            {judged} of {total}
            {" · "}
            <ElapsedSince iso={run.summary.uploaded_at} />
            {" · "}
            {fmtUsd(run.summary.cost_usd)} spent
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Disclosures judged"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct)}
          aria-valuetext={`${judged} of ${total} disclosures judged`}
          className="h-1.5 w-full overflow-hidden rounded-[3px] bg-soft-2"
        >
          <div
            className="h-full bg-accent transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-[15px] font-semibold text-ink">
          Findings — streaming live
        </h2>
        <span className="text-xs text-muted-ink">
          {judged} judged
          {total > judged ? ` · ${total - judged} in queue` : ""}
        </span>
      </div>
      <div
        aria-live="polite"
        className="min-h-0 flex-1 overflow-y-auto rounded-3xl bg-surface"
      >
        {[...run.findings].reverse().map((f) => (
          <div key={f.disclosure_id} className="border-b border-line last:border-0">
            <FeedRow finding={f} title={titles.get(f.disclosure_id)} />
          </div>
        ))}
        {run.summary.status === "judging" && (
          <div className="flex h-[52px] items-center gap-3.5 px-4 text-muted-ink">
            <Loader2 className="size-5 animate-spin" aria-hidden />
            <span className="text-[13px] font-medium">
              Judging next disclosure…
            </span>
          </div>
        )}
        {judged === 0 && run.summary.status !== "judging" && (
          <div className="grid h-40 place-items-center text-[13px] text-muted-ink">
            Findings appear here once judging begins.
          </div>
        )}
      </div>
    </>
  );
}

function ElapsedSince({ iso }: { iso: string }) {
  const [now, setNow] = useState(() => Date.now());
  const start = useRef(new Date(iso).getTime());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = Math.max(0, Math.floor((now - start.current) / 1000));
  const m = Math.floor(s / 60);
  return (
    <span>
      {m}:{String(s % 60).padStart(2, "0")} elapsed
    </span>
  );
}

export function fmtUsd(v: number): string {
  return `$${v.toFixed(2)}`;
}
