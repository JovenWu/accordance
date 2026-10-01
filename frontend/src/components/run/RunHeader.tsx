import { useState } from "react";
import { FileDown, OctagonX, RotateCcw, Terminal } from "lucide-react";

import { retryRun, stopRun, exportRunCoverageUrl } from "@/api";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { useToast } from "@/components/ui/toast";
import type { RunDetail } from "@/types";

const LIVE = ["queued", "extracting", "indexing", "judging"];

export function RunHeader({
  run,
  onChanged,
  onOpenTraces,
}: {
  run: RunDetail;
  onChanged: () => void;
  onOpenTraces?: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<"cancel" | "retry" | null>(null);
  const status = run.summary.status;
  const isLive = LIVE.includes(status);

  async function cancel() {
    setBusy("cancel");
    try {
      await stopRun(run.summary.id);
      toast("Run cancelled");
      onChanged();
    } catch (e) {
      toast("Cancel failed", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(null);
    }
  }

  async function retry() {
    setBusy("retry");
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
      setBusy(null);
    }
  }

  const title =
    status === "completed" || status === "cancelled"
      ? `Run v${run.version_number} — findings`
      : `Run v${run.version_number} — ${run.kind}`;

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold text-ink">{title}</h1>
        {isLive && (
          <Chip tone="accent">
            <span aria-hidden>●</span> Live
          </Chip>
        )}
        {status === "failed" && <Chip tone="danger">Failed</Chip>}
        {status === "completed" && <Chip tone="success">Completed</Chip>}
        {status === "cancelled" && <Chip>Cancelled</Chip>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {isLive && (
          <Button
            variant="danger-soft"
            size="sm"
            icon={<OctagonX />}
            busy={busy === "cancel"}
            onClick={() => void cancel()}
          >
            Cancel run
          </Button>
        )}
        {status === "failed" && (
          <Button
            size="sm"
            icon={<RotateCcw />}
            busy={busy === "retry"}
            onClick={() => void retry()}
          >
            Retry run
          </Button>
        )}
        {(status === "completed" || status === "cancelled") && (
          <>
            <Button
              variant="outline"
              size="sm"
              icon={<RotateCcw />}
              busy={busy === "retry"}
              onClick={() => void retry()}
            >
              Retry
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<Terminal />}
              onClick={onOpenTraces}
            >
              Traces
            </Button>
            <Button size="sm" icon={<FileDown />} asChild>
              <a href={exportRunCoverageUrl(run.summary.id)} download>
                Export
              </a>
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
