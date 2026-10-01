import { createContext, useContext } from "react";

import type { FindingView } from "@/types";

export interface EvidenceViewerValue {
  /** Open the evidence screen for a finding (jumps to its cited page and
   * highlights the excerpt in the text layer). */
  openEvidence: (finding: FindingView) => void;
}

export const Ctx = createContext<EvidenceViewerValue | null>(null);

export function useEvidenceViewer(): EvidenceViewerValue {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error(
      "useEvidenceViewer must be used within an EvidenceViewerProvider",
    );
  }
  return v;
}
