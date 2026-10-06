import { describe, expect, it } from "vitest";

import {
  completenessPct,
  effectiveFindings,
  effectiveGrade,
  scoreDistribution,
  scoreMeta,
} from "@/lib/score";
import type { FindingView } from "@/types";
import type { CorrectionView } from "@/types";

const corr: CorrectionView = {
  id: 1, disclosure_id: "2-1", corrected_score: 5, corrected_elements: null,
  rationale: "x", agent_score: 3, reviewer: "assessor", created_at: "2026-06-18",
};

function f(score: number | null, status: FindingView["status"] = "covered"): FindingView {
  return {
    disclosure_id: "x",
    standard: "GRI 2",
    status,
    score,
    na_reason: null,
    note: "",
    evidence_excerpt: null,
    evidence_page: null,
    elements: [],
    suggested_fix: "",
    vision_fallback_used: false,
  } as FindingView;
}

describe("scoreMeta", () => {
  it("labels each score band", () => {
    expect(scoreMeta(5).label).toBe("Complete");
    expect(scoreMeta(4).label).toBe("Substantial");
    expect(scoreMeta(3).label).toBe("Partial");
    expect(scoreMeta(2).label).toBe("Minimal");
    expect(scoreMeta(1).label).toBe("Missing");
    expect(scoreMeta(0).label).toBe("N/A");
  });
  it("maps tiers to existing tokens", () => {
    expect(scoreMeta(5).textClass).toContain("success");
    expect(scoreMeta(3).textClass).toContain("warning");
    expect(scoreMeta(1).textClass).toContain("danger");
    expect(scoreMeta(0).textClass).toContain("muted");
  });
  it("treats null score as a judge error", () => {
    expect(scoreMeta(null).label).toBe("Judge error");
    expect(scoreMeta(null).textClass).toContain("danger");
  });
});

describe("completenessPct", () => {
  it("averages score/5 over applicable disclosures (excludes N/A and error)", () => {
    expect(completenessPct([f(5), f(5), f(0), f(null, "error")])).toBe(100);
    expect(completenessPct([f(5), f(3)])).toBe(80);
  });
  it("rounds to one decimal place", () => {
    expect(completenessPct([f(5), f(4), f(4)])).toBe(86.7);
  });
  it("returns null when there are no applicable disclosures", () => {
    expect(completenessPct([f(0), f(null, "error")])).toBeNull();
    expect(completenessPct([])).toBeNull();
  });
});

describe("effectiveGrade", () => {
  it("returns the agent score when there is no correction", () => {
    expect(effectiveGrade(3, null)).toEqual({ score: 3, corrected: false });
    expect(effectiveGrade(null, undefined)).toEqual({ score: null, corrected: false });
  });
  it("returns the corrected score, flagged, when a correction exists", () => {
    expect(effectiveGrade(3, corr)).toEqual({ score: 5, corrected: true });
  });
});

describe("scoreDistribution", () => {
  it("counts findings per score 0..5 (null grouped under 'error')", () => {
    const d = scoreDistribution([f(5), f(5), f(3), f(0), f(null, "error")]);
    expect(d[5]).toBe(2);
    expect(d[3]).toBe(1);
    expect(d[0]).toBe(1);
    expect(d.error).toBe(1);
    expect(d[4]).toBe(0);
  });
});

describe("effectiveFindings", () => {
  const mk = (id: string, score: number | null): FindingView => ({
    disclosure_id: id, standard: "GRI 2", status: "covered", score,
    na_reason: null, note: "", evidence_excerpt: null, evidence_page: null,
    elements: [], suggested_fix: "", vision_fallback_used: false,
  });

  it("overrides a finding's score with the live correction's corrected_score", () => {
    const findings = [mk("2-1", 3), mk("2-2", 5)];
    const corrections = {
      "2-1": { ...corr, disclosure_id: "2-1", corrected_score: 4 },
    };
    const out = effectiveFindings(findings, corrections);
    expect(out.find((f) => f.disclosure_id === "2-1")!.score).toBe(4);
    expect(out.find((f) => f.disclosure_id === "2-2")!.score).toBe(5);
  });

  it("applies a correction to 0 so the aggregate treats it as N/A", () => {
    const findings = [mk("2-1", 5)];
    const corrections = { "2-1": { ...corr, disclosure_id: "2-1", corrected_score: 0 } };
    const out = effectiveFindings(findings, corrections);
    expect(out[0].score).toBe(0);
    expect(completenessPct(out)).toBe(null);
  });

  it("returns findings unchanged with no corrections", () => {
    const findings = [mk("2-1", 3)];
    expect(effectiveFindings(findings, {})).toEqual(findings);
    expect(effectiveFindings(findings, undefined)).toEqual(findings);
  });
});
