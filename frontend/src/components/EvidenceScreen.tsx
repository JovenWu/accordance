import { Suspense, lazy, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Minus,
  PenLine,
  Plus,
  Terminal,
  X,
  Check,
} from "lucide-react";

import { pdfUrl } from "@/api";
import { Button } from "@/components/ui/button";
import { DisclosureStatusChip, ScorePill } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useKbTitles } from "@/lib/useKbTitles";
import { cn } from "@/lib/utils";
import type { ElementJudgment, FindingView } from "@/types";

const PdfViewer = lazy(() => import("@/components/PdfViewer"));

const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEP = 0.2;
const LETTER = "abcdefgh";
const clamp = (n: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, n));

const EL_ICONS = { found: Check, partial: Minus, missing: X } as const;
const EL_TONE = {
  found: "text-success",
  partial: "text-warning",
  missing: "text-danger",
} as const;

/** Full evidence screen (design M2P6bQ): finding context on the left, the PDF
 * viewer on the right, scrolled to the cited page with the excerpt marked. */
export function EvidenceScreen({
  requestKey,
  runId,
  pdfFilename,
  versionNumber,
  finding,
  onClose,
  onCorrect,
  onTrace,
}: {
  requestKey: number;
  runId: string;
  pdfFilename: string;
  versionNumber: number;
  finding: FindingView;
  onClose: () => void;
  onCorrect?: (f: FindingView) => void;
  onTrace?: (f: FindingView) => void;
}) {
  const titles = useKbTitles();
  const citedPage = finding.evidence_page ?? 1;
  const [page, setPage] = useState(citedPage);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const bodyRef = useRef<HTMLDivElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const anchorRef = useRef<{ fx: number; fy: number } | null>(null);

  const effectivePage = numPages ? Math.min(page, numPages) : page;
  const atStart = effectivePage <= 1;
  const atEnd = numPages !== null && effectivePage >= numPages;
  // The excerpt only exists on its cited page — never highlight elsewhere.
  const onCitedPage = effectivePage === citedPage;
  const activeHighlight = onCitedPage ? finding.evidence_excerpt : null;

  useEffect(() => {
    setPage(citedPage);
  }, [requestKey, citedPage]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The screen swaps in over the findings view, unmounting the opener — move
  // focus into it once (the back button) so keyboard users aren't left on body.
  useEffect(() => {
    backRef.current?.focus();
  }, []);

  function goTo(n: number) {
    setPage(clamp(n, 1, numPages ?? n));
  }

  function zoomTo(next: number) {
    const b = bodyRef.current;
    if (b) {
      anchorRef.current = {
        fx:
          b.scrollWidth > b.clientWidth
            ? (b.scrollLeft + b.clientWidth / 2) / b.scrollWidth
            : 0.5,
        fy:
          b.scrollHeight > b.clientHeight
            ? (b.scrollTop + b.clientHeight / 2) / b.scrollHeight
            : 0.5,
      };
    }
    setZoom(clamp(next, ZOOM_MIN, ZOOM_MAX));
  }

  function handleRendered() {
    const a = anchorRef.current;
    if (!a) return;
    anchorRef.current = null;
    requestAnimationFrame(() => {
      const b = bodyRef.current;
      if (!b) return;
      b.scrollLeft = a.fx * b.scrollWidth - b.clientWidth / 2;
      b.scrollTop = a.fy * b.scrollHeight - b.clientHeight / 2;
    });
  }

  const found = finding.elements.filter((e) => e.status === "found").length;
  const title = titles.get(finding.disclosure_id);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <button
        ref={backRef}
        type="button"
        onClick={onClose}
        className="flex w-fit items-center gap-1.5 rounded-md text-[13px] text-muted-ink hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
      >
        <ChevronLeft className="size-4 -rotate-0" aria-hidden />
        <span className="font-medium">Run v{versionNumber} — findings</span>
        <span>/ {finding.disclosure_id} evidence</span>
      </button>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-lg font-semibold text-ink">
          {finding.disclosure_id}
          {title ? ` — ${title}` : ""}
        </h1>
        <DisclosureStatusChip
          status={finding.status}
          na={finding.score === 0}
        />
        <ScorePill score={finding.score} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto lg:flex-row lg:items-stretch lg:overflow-visible">
        {/* Left: judge context */}
        <div className="flex w-full shrink-0 flex-col gap-3.5 lg:w-[400px] lg:overflow-y-auto">
          <div className="flex flex-col gap-2 rounded-3xl bg-surface p-4">
            <span className="text-[11px] font-semibold text-muted-ink">
              Judge note
            </span>
            <p className="text-[13px]/[20px] text-ink">
              {finding.na_reason
                ? `Not applicable — ${finding.na_reason}`
                : finding.note}
            </p>
          </div>
          {finding.elements.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-3xl bg-surface p-4">
              <span className="text-[11px] font-semibold text-muted-ink">
                Required elements — {found} of {finding.elements.length} found
              </span>
              {finding.elements.map((el: ElementJudgment, i: number) => {
                const Icon = EL_ICONS[el.status];
                return (
                  <div key={el.id} className="flex items-center gap-2">
                    <Icon
                      className={cn("size-3.5", EL_TONE[el.status])}
                      role="img"
                      aria-label={el.status}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs text-ink">
                      {LETTER[i] ?? i + 1}) {el.id.replace(/_/g, " ")}
                    </span>
                    {el.page != null && (
                      <span className="text-[11px] text-muted-ink">
                        p.{el.page}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {finding.suggested_fix && (
            <div className="flex flex-col gap-1.5 rounded-3xl bg-surface p-4">
              <span className="text-[11px] font-semibold text-muted-ink">
                Suggested fix
              </span>
              <p className="text-xs/[17px] text-ink">{finding.suggested_fix}</p>
            </div>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              icon={<PenLine />}
              onClick={() => onCorrect?.(finding)}
            >
              Correct finding
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<Terminal />}
              onClick={() => onTrace?.(finding)}
            >
              View trace
            </Button>
          </div>
        </div>

        {/* Right: PDF viewer */}
        <div className="flex min-h-[420px] min-w-0 flex-1 flex-col gap-2.5 lg:min-h-0">
          <div className="flex flex-wrap items-center gap-2 bg-surface px-3 py-2">
            <FileText className="size-4 shrink-0 text-muted-ink" aria-hidden />
            <span className="truncate text-xs font-medium text-ink">
              {pdfFilename}
            </span>
            <Button
              variant="flat"
              size="icon"
              onClick={() => goTo(effectivePage - 1)}
              disabled={atStart}
              aria-label="Previous page"
            >
              <ChevronLeft aria-hidden />
            </Button>
            <span
              aria-live="polite"
              className="whitespace-nowrap text-xs tabular-nums text-muted-ink"
            >
              Page {effectivePage} of {numPages ?? "…"}
            </span>
            <Button
              variant="flat"
              size="icon"
              onClick={() => goTo(effectivePage + 1)}
              disabled={atEnd}
              aria-label="Next page"
            >
              <ChevronRight aria-hidden />
            </Button>
            <span className="flex-1" />
            {activeHighlight ? (
              <span className="rounded-2xl bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">
                Evidence match · p.{citedPage}
              </span>
            ) : finding.evidence_page != null && !onCitedPage ? (
              <button
                type="button"
                onClick={() => goTo(citedPage)}
                className="rounded-2xl bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
              >
                Evidence on p.{citedPage} — jump back
              </button>
            ) : null}
            <Button
              variant="flat"
              size="icon"
              onClick={() => zoomTo(zoom - ZOOM_STEP)}
              disabled={zoom <= ZOOM_MIN}
              aria-label="Zoom out"
            >
              <Minus aria-hidden />
            </Button>
            <button
              type="button"
              onClick={() => zoomTo(1)}
              className="w-11 rounded-md text-center text-xs tabular-nums text-muted-ink hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
              aria-label="Reset zoom"
            >
              {Math.round(zoom * 100)}%
            </button>
            <Button
              variant="flat"
              size="icon"
              onClick={() => zoomTo(zoom + ZOOM_STEP)}
              disabled={zoom >= ZOOM_MAX}
              aria-label="Zoom in"
            >
              <Plus aria-hidden />
            </Button>
            <Button variant="flat" size="icon" asChild aria-label="Download PDF">
              <a href={pdfUrl(runId)} download={pdfFilename}>
                <Download aria-hidden />
              </a>
            </Button>
            <Button
              variant="flat"
              size="icon"
              onClick={onClose}
              aria-label="Close evidence"
            >
              <X aria-hidden />
            </Button>
          </div>
          <div
            ref={bodyRef}
            className="min-h-0 flex-1 overflow-auto rounded-3xl bg-soft-2 p-6"
          >
            <Suspense
              fallback={
                <Skeleton className="mx-auto aspect-[1/1.3] w-full max-w-[680px]" />
              }
            >
              <PdfViewer
                url={pdfUrl(runId)}
                page={effectivePage}
                highlight={activeHighlight}
                zoom={zoom}
                onNumPages={setNumPages}
                onRendered={handleRendered}
              />
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
}
