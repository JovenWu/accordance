import type { FindingView, CorrectionView } from "@/types";

/** The grade to display for a disclosure: the assessor's correction when one
 * exists (authoritative), else the agent's score. */
export function effectiveGrade(
  agentScore: number | null,
  correction?: CorrectionView | null,
): { score: number | null; corrected: boolean } {
  if (correction) return { score: correction.corrected_score, corrected: true };
  return { score: agentScore, corrected: false };
}

/** Findings with each score overridden by the live assessor correction (when
 * one exists), so aggregate views (completeness %, distribution) reflect saved
 * feedback the same way the per-row pills do via effectiveGrade. */
export function effectiveFindings(
  findings: FindingView[],
  correctionsByDisclosure?: Record<string, CorrectionView>,
): FindingView[] {
  if (!correctionsByDisclosure) return findings;
  return findings.map((f) => {
    const c = correctionsByDisclosure[f.disclosure_id];
    return c ? { ...f, score: c.corrected_score } : f;
  });
}

export interface ScoreMeta {
  label: string;
  /** Tailwind text color class (existing semantic token). */
  textClass: string;
  /** Tailwind bg color class for dots/pills. */
  dotClass: string;
}

const META_BY_SCORE: Record<number, ScoreMeta> = {
  5: { label: "Complete", textClass: "text-success", dotClass: "bg-success" },
  4: { label: "Substantial", textClass: "text-success", dotClass: "bg-success" },
  3: { label: "Partial", textClass: "text-warning", dotClass: "bg-warning" },
  2: { label: "Minimal", textClass: "text-warning", dotClass: "bg-warning" },
  1: { label: "Missing", textClass: "text-danger", dotClass: "bg-danger" },
  0: { label: "N/A", textClass: "text-muted-ink", dotClass: "bg-muted-ink" },
};

const ERROR_META: ScoreMeta = {
  label: "Judge error",
  textClass: "text-danger",
  dotClass: "bg-danger",
};

/** Display metadata for a 0-5 score. null (ungraded/error) -> Judge error. */
export function scoreMeta(score: number | null): ScoreMeta {
  if (score === null || META_BY_SCORE[score] === undefined) return ERROR_META;
  return META_BY_SCORE[score];
}

function isApplicable(f: FindingView): boolean {
  return f.score !== null && f.score > 0;
}

/** Mean of score/5 over applicable disclosures, as a 0-100 number rounded to
 * one decimal place; null when none are applicable. */
export function completenessPct(findings: FindingView[]): number | null {
  const applicable = findings.filter(isApplicable);
  if (applicable.length === 0) return null;
  const mean =
    applicable.reduce((sum, f) => sum + (f.score as number) / 5, 0) /
    applicable.length;
  return Math.round(mean * 1000) / 10;
}

export interface ScoreDistribution {
  0: number;
  1: number;
  2: number;
  3: number;
  4: number;
  5: number;
  error: number;
}

/** Count findings per score 0..5; null/unknown scores grouped under `error`. */
export function scoreDistribution(findings: FindingView[]): ScoreDistribution {
  const d: ScoreDistribution = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, error: 0 };
  for (const f of findings) {
    const score = f.score;
    if (score === null || META_BY_SCORE[score] === undefined) d.error += 1;
    else d[score as 0 | 1 | 2 | 3 | 4 | 5] += 1;
  }
  return d;
}
