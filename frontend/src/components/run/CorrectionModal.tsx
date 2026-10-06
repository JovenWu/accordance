import { useState } from "react";
import { Check, Minus, X } from "lucide-react";

import { saveCorrection } from "@/api";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/auth/auth-context";
import { scoreMeta } from "@/lib/score";
import { cn } from "@/lib/utils";
import type {
  CorrectionView,
  ElementJudgment,
  FindingView,
  RunDetail,
} from "@/types";

const SCORE_LABEL: Record<number, string> = {
  0: "0 · N/A",
  1: "1 · Missing",
  5: "5 · Complete",
};

const LETTER = "abcdefgh";
const EL_STATES = ["found", "partial", "missing"] as const;
const EL_ICONS = { found: Check, partial: Minus, missing: X } as const;
const EL_TONES = {
  found: "bg-success text-white",
  partial: "bg-warning text-white",
  missing: "bg-danger text-white",
} as const;

export function CorrectionModal({
  run,
  finding,
  existing,
  onClose,
  onSaved,
}: {
  run: RunDetail;
  finding: FindingView;
  existing?: CorrectionView;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const { username } = useAuth();
  const [score, setScore] = useState<number>(
    existing?.corrected_score ?? finding.score ?? 0,
  );
  const [elements, setElements] = useState<ElementJudgment[]>(
    existing?.corrected_elements ?? finding.elements,
  );
  const [rationale, setRationale] = useState(existing?.rationale ?? "");
  const [saving, setSaving] = useState(false);

  const matchesAgent =
    score === finding.score &&
    elements.every((el, i) => el.status === finding.elements[i]?.status);

  async function save() {
    setSaving(true);
    try {
      await saveCorrection(run.summary.id, {
        disclosure_id: finding.disclosure_id,
        corrected_score: score,
        corrected_elements: elements,
        rationale: rationale.trim(),
      });
      toast("Correction saved", {
        message: `${finding.disclosure_id} → ${score}/5`,
      });
      onSaved();
    } catch (e) {
      toast("Could not save correction", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      title={
        <span className="flex flex-col gap-0.5">
          <span>Correct finding</span>
          <span className="text-xs font-normal text-muted-ink">
            {finding.disclosure_id} · agent score{" "}
            {finding.score ?? "!"} ({finding.status})
          </span>
        </span>
      }
      onClose={onClose}
      className="w-[560px]"
      footer={
        <>
          <span className="mr-auto text-[11px] text-muted-ink">
            Applies to run v{run.version_number} · recorded as{" "}
            {username}
          </span>
          <Button variant="flat" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            busy={saving}
            disabled={rationale.trim().length === 0}
            onClick={() => void save()}
          >
            Save correction
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-ink">
            Corrected score
          </span>
          <div
            className="flex gap-1.5"
            role="radiogroup"
            aria-label="Corrected score"
            onKeyDown={(e) => {
              const next =
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? 5
                    : e.key === "ArrowRight" || e.key === "ArrowDown"
                      ? (score + 1) % 6
                      : e.key === "ArrowLeft" || e.key === "ArrowUp"
                        ? (score + 5) % 6
                        : -1;
              if (next < 0) return;
              e.preventDefault();
              setScore(next);
              e.currentTarget.querySelectorAll("button")[next]?.focus();
            }}
          >
            {[0, 1, 2, 3, 4, 5].map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={score === s}
                tabIndex={score === s ? 0 : -1}
                onClick={() => setScore(s)}
                className={cn(
                  "h-8 flex-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  score === s
                    ? "bg-accent text-accent-ink"
                    : "bg-soft-2 text-ink hover:bg-soft",
                )}
              >
                {SCORE_LABEL[s] ?? s}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-muted-ink">
            Selected: {score} · {scoreMeta(score).label}
            {matchesAgent ? " — matches agent judgment" : ""}
          </span>
        </div>

        {elements.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-ink">
              Per-element overrides — optional
            </span>
            {elements.map((el, i) => (
              <div key={el.id} className="flex items-center gap-2.5">
                <span className="min-w-0 flex-1 truncate text-xs text-ink">
                  {LETTER[i] ?? i + 1}) {el.id.replace(/_/g, " ")}
                </span>
                <span className="flex gap-0.5 bg-soft-2 p-0.5">
                  {EL_STATES.map((st) => {
                    const Icon = EL_ICONS[st];
                    const active = el.status === st;
                    return (
                      <button
                        key={st}
                        type="button"
                        aria-label={`${el.id}: ${st}`}
                        aria-pressed={active}
                        onClick={() =>
                          setElements((cur) =>
                            cur.map((x, j) =>
                              j === i ? { ...x, status: st } : x,
                            ),
                          )
                        }
                        className={cn(
                          "grid h-[22px] w-6 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 [&_svg]:size-3",
                          active
                            ? EL_TONES[st]
                            : "text-muted-ink hover:text-ink",
                        )}
                      >
                        <Icon aria-hidden />
                      </button>
                    );
                  })}
                </span>
              </div>
            ))}
          </div>
        )}

        <label className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-ink">
            Rationale — required
          </span>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={3}
            placeholder="Why is the agent score wrong?"
            className="w-full resize-none rounded-xl bg-soft px-3 py-2.5 text-[13px]/[18px] text-ink outline-none placeholder:text-muted-ink focus:ring-2 focus:ring-ring/40"
          />
        </label>
      </div>
    </Modal>
  );
}
