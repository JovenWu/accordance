import { useCallback, useMemo, useState } from "react";

import { EvidenceScreen } from "@/components/EvidenceScreen";
import { Ctx, type EvidenceViewerValue } from "./evidence-viewer-context";
import type { FindingView } from "@/types";

interface EvidenceRequest {
  finding: FindingView;
  key: number; // increments per open so the panel can retarget via requestKey without remounting
}

export function EvidenceViewerProvider({
  runId,
  pdfFilename,
  versionNumber,
  onCorrect,
  onTrace,
  children,
}: {
  runId: string;
  pdfFilename: string;
  versionNumber: number;
  onCorrect?: (f: FindingView) => void;
  onTrace?: (f: FindingView) => void;
  children: React.ReactNode;
}) {
  const [request, setRequest] = useState<EvidenceRequest | null>(null);

  const openEvidence = useCallback((finding: FindingView) => {
    setRequest((prev) => ({ finding, key: (prev?.key ?? 0) + 1 }));
  }, []);

  const value: EvidenceViewerValue = useMemo(
    () => ({ openEvidence }),
    [openEvidence],
  );

  return (
    <Ctx.Provider value={value}>
      {request ? (
        <EvidenceScreen
          // No `key` here on purpose: re-keying would remount the <Document>
          // and race the pdf.js worker (destroy + create) → blank PDF. The
          // screen stays mounted and just retargets via requestKey instead.
          requestKey={request.key}
          runId={runId}
          pdfFilename={pdfFilename}
          versionNumber={versionNumber}
          finding={request.finding}
          onClose={() => setRequest(null)}
          onCorrect={onCorrect}
          onTrace={onTrace}
        />
      ) : (
        children
      )}
    </Ctx.Provider>
  );
}
