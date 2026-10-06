import { createContext, useContext } from "react";

import type { FindingView } from "@/types";

export interface EvidenceViewerValue {
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
