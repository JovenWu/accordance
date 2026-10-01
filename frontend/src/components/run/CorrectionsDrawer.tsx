import { useState } from "react";
import { Trash2 } from "lucide-react";

import { deleteCorrection } from "@/api";
import { Chip } from "@/components/ui/chip";
import { Drawer } from "@/components/ui/drawer";
import { useToast } from "@/components/ui/toast";
import { formatDateTime } from "@/lib/datetime";
import type { CorrectionView, RunDetail } from "@/types";

function elementSummary(c: CorrectionView): string {
  const els = c.corrected_elements;
  if (!els || els.length === 0) return "score only";
  const found = els.filter((e) => e.status === "found").length;
  if (found === els.length) return "all elements";
  if (found === 0) return "all missing";
  return "partial elements";
}

function chipTone(score: number): "accent" | "danger" | "neutral" {
  if (score >= 3) return "accent";
  if (score >= 1) return "danger";
  return "neutral";
}

export function CorrectionsDrawer({
  run,
  titles,
  onClose,
  onChanged,
}: {
  run: RunDetail;
  titles: Map<string, string>;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [deleting, setDeleting] = useState<number | null>(null);

  async function remove(c: CorrectionView) {
    setDeleting(c.id);
    try {
      await deleteCorrection(run.summary.id, c.id);
      toast("Correction removed", { message: c.disclosure_id });
      onChanged();
    } catch (e) {
      toast("Could not remove correction", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setDeleting(null);
    }
  }

  return (
    <Drawer
      open
      title="Corrections"
      subtitle={`Run v${run.version_number} · ${run.corrections.length} live overrides`}
      onClose={onClose}
      className="w-[440px]"
    >
      <div className="flex flex-col gap-3 p-4">
        {run.corrections.map((c) => (
          <div
            key={c.id}
            className="flex flex-col gap-2 rounded-xl bg-surface p-3.5 shadow-[0_1px_2px_#0000000F]"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Chip tone={chipTone(c.corrected_score)} size="lg">
                  Score {c.corrected_score} · {elementSummary(c)}
                </Chip>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-ink">
                  {formatDateTime(c.created_at, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                <button
                  type="button"
                  aria-label={`Delete correction for ${c.disclosure_id}`}
                  disabled={deleting === c.id}
                  onClick={() => void remove(c)}
                  className="grid size-6 place-items-center rounded-xl bg-soft text-muted-ink transition-colors hover:bg-danger-soft hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 disabled:opacity-50"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </div>
            </div>
            <p className="text-xs text-ink">{c.rationale}</p>
            <span className="text-[11px] text-muted-ink">
              {c.disclosure_id}
              {titles.get(c.disclosure_id)
                ? ` — ${titles.get(c.disclosure_id)}`
                : ""}{" "}
              · {c.reviewer}
              {c.agent_score != null
                ? ` · agent score ${c.agent_score}`
                : ""}
            </span>
          </div>
        ))}
        {run.corrections.length === 0 && (
          <p className="py-10 text-center text-[13px] text-muted-ink">
            No corrections yet — expand a finding and press Correct.
          </p>
        )}
      </div>
    </Drawer>
  );
}
