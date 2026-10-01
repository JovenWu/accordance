import { useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  FileDown,
  FileSpreadsheet,
  FileText,
  ListPlus,
  OctagonX,
  RotateCcw,
  Terminal,
} from "lucide-react";

import {
  exportRunAnalysisUrl,
  exportRunCoverageUrl,
  getKb,
  getPresets,
  judgeMore,
  retryRun,
  stopRun,
} from "@/api";
import { ScopeModal } from "@/components/ScopeModal";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { KebabMenu } from "@/components/ui/menu";
import { useToast } from "@/components/ui/toast";
import type { KbStandard, Preset, RunDetail } from "@/types";

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
  const [busy, setBusy] = useState<"cancel" | "retry" | "scope" | null>(null);
  const [scope, setScope] = useState<{
    groups: KbStandard[];
    presets: Preset[];
  } | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  // Stable identity — a fresh Set each render would reset ScopeModal's draft.
  const emptySelection = useRef(new Set<string>()).current;
  const status = run.summary.status;
  const isLive = LIVE.includes(status);

  // The backend skips disclosures that already have a non-error finding, so
  // they show as locked here; errored findings stay selectable for re-judging.
  const judged = useMemo(
    () =>
      new Set(
        run.findings
          .filter((f) => f.status !== "error")
          .map((f) => f.disclosure_id),
      ),
    [run.findings],
  );

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

  async function openScope() {
    setBusy("scope");
    try {
      if (!scope) {
        const [groups, presets] = await Promise.all([getKb(), getPresets()]);
        setScope({ groups, presets });
      }
      setScopeOpen(true);
    } catch (e) {
      toast("Couldn't load the disclosure catalog", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(null);
    }
  }

  async function judgeSelection(next: Set<string>) {
    try {
      const res = await judgeMore(run.summary.id, [...next]);
      toast(
        res.judged.length > 0
          ? `Judging ${res.judged.length} more disclosure${res.judged.length === 1 ? "" : "s"}`
          : "Nothing new to judge",
        {
          message:
            res.judged.length > 0
              ? "The run re-enters judging; findings appear as they land."
              : "Every selected disclosure already has a finding.",
        },
      );
      onChanged();
    } catch (e) {
      toast("Couldn't start judge-more", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
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
        {!isLive && (
          <Button
            variant="outline"
            size="sm"
            icon={<ListPlus />}
            busy={busy === "scope"}
            onClick={() => void openScope()}
          >
            Add disclosures
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
            <KebabMenu
              label="Export"
              trigger={
                <Button size="sm" icon={<FileDown />}>
                  Export
                  <ChevronDown aria-hidden />
                </Button>
              }
              items={[
                {
                  label: "Excel — coverage matrix",
                  icon: <FileSpreadsheet />,
                  onSelect: () =>
                    window.open(exportRunCoverageUrl(run.summary.id), "_self"),
                },
                {
                  label: "PDF — analysis report",
                  icon: <FileText />,
                  disabled: status !== "completed",
                  onSelect: () =>
                    window.open(exportRunAnalysisUrl(run.summary.id), "_self"),
                },
              ]}
            />
          </>
        )}
      </div>
      {scopeOpen && scope && (
        <ScopeModal
          open={scopeOpen}
          onClose={() => setScopeOpen(false)}
          groups={scope.groups}
          presets={scope.presets}
          selected={emptySelection}
          locked={judged}
          onApply={(next) => void judgeSelection(next)}
        />
      )}
    </div>
  );
}
