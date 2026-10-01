import { useEffect, useRef, useState } from "react";

export interface SSEEvent {
  type: string;
  [k: string]: unknown;
}

export function useSSE(runId: string | null, onEvent: (e: SSEEvent) => void) {
  const [open, setOpen] = useState(false);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/runs/${runId}/stream`);
    es.onopen = () => setOpen(true);
    es.onmessage = (m) => {
      try {
        const data = JSON.parse(m.data);
        handlerRef.current(data);
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => setOpen(false);
    return () => es.close();
  }, [runId]);

  return { open };
}
