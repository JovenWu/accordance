import { useCallback, useMemo, useState } from "react";

import { EvidenceScreen } from "@/components/EvidenceScreen";
import { Ctx, type EvidenceViewerValue } from "./evidence-viewer-context";
import type { FindingView } from "@/types";

interface EvidenceRequest {
  finding: FindingView;
  key: number;
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
