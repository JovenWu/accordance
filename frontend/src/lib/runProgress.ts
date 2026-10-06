import type { RunStatus } from "@/types";

export function progressPct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}

export function phaseLabel(status: RunStatus): string {
  switch (status) {
    case "queued":
      return "Queued…";
    case "extracting":
      return "Extracting PDF…";
    case "indexing":
      return "Indexing…";
    case "judging":
      return "Judging disclosures…";
    default:
      return "";
  }
}
