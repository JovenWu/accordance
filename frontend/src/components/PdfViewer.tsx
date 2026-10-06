import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { TextContent } from "react-pdf";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import "react-pdf/dist/Page/TextLayer.css";
import PdfjsWorker from "pdfjs-dist/build/pdf.worker.min.mjs?worker";

import {
  computeHighlightRanges,
  markItem,
  type PdfTextItem,
} from "@/lib/evidenceMatch";

if (!pdfjs.GlobalWorkerOptions.workerPort) {
  pdfjs.GlobalWorkerOptions.workerPort = new PdfjsWorker();
}

const DPR =
  typeof window !== "undefined" ? Math.min(window.devicePixelRatio || 1, 3) : 1;

const GUTTER = 24;

export default function PdfViewer({
  url,
  page,
  highlight,
  zoom = 1,
  onNumPages,
  onRendered,
}: {
  url: string;
  page: number;
  highlight: string | null;
  zoom?: number;
  onNumPages?: (n: number) => void;
  onRendered?: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [ranges, setRanges] = useState<Map<number, [number, number]> | null>(
    null,
  );
  const [fitWidth, setFitWidth] = useState(640);
  const stageRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const scrolledKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0].contentRect.width) - GUTTER;
      if (w > 0) setFitWidth((prev) => (Math.abs(prev - w) > 2 ? w : prev));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onGetTextSuccess = useCallback(
    (textContent: TextContent) => {
      const items: PdfTextItem[] = textContent.items.map((it) =>
        "str" in it
          ? { str: it.str, hasEOL: it.hasEOL }
          : { str: "", hasEOL: false },
      );
      setRanges(computeHighlightRanges(items, highlight));
    },
    [highlight],
  );

  const customTextRenderer = useCallback(
    ({ str, itemIndex }: { str: string; itemIndex: number }) =>
      markItem(str, ranges?.get(itemIndex)),
    [ranges],
  );

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-sm text-muted-ink">
        <p>{error}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setError(null);
            setRetryKey((k) => k + 1);
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  const renderWidth = Math.max(120, Math.round(fitWidth * zoom));

  return (
    <div ref={measureRef} className="w-full">
      <div ref={stageRef} className="mx-auto w-max px-3 py-0">
        <Document
          key={retryKey}
          file={url}
          loading={
            <Skeleton
              role="status"
              className="relative rounded-md"
              style={{ width: renderWidth, height: Math.round(renderWidth * 1.3) }}
            >
              <span className="sr-only">Loading PDF page…</span>
            </Skeleton>
          }
          onLoadSuccess={(doc) => onNumPages?.(doc.numPages)}
          onLoadError={() => setError("Couldn't load the source PDF.")}
        >
          <Page
            pageNumber={page}
            width={renderWidth}
            devicePixelRatio={DPR}
            renderAnnotationLayer={false}
            className="overflow-hidden rounded-md shadow-sm ring-1 ring-line"
            onGetTextSuccess={onGetTextSuccess}
            customTextRenderer={customTextRenderer}
            onRenderSuccess={() => onRendered?.()}
            onRenderError={() => setError("Couldn't render this page.")}
            onRenderTextLayerSuccess={() => {
              const key = `${page}::${highlight ?? ""}`;
              if (scrolledKeyRef.current === key) return;
              scrolledKeyRef.current = key;
              stageRef.current
                ?.querySelector("mark")
                ?.scrollIntoView({ block: "center" });
            }}
          />
        </Document>
      </div>
    </div>
  );
}
