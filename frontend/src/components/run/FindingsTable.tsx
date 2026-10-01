import { Check, ChevronDown, ChevronUp, FileText, Minus, PenLine, Terminal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Chip, DisclosureStatusChip, ScorePill } from "@/components/ui/chip";
import { useEvidenceViewer } from "@/components/evidence-viewer-context";
import { effectiveGrade } from "@/lib/score";
import { cn } from "@/lib/utils";
import type {
  CorrectionView,
  DisclosureStatus,
  ElementJudgment,
  FindingView,
} from "@/types";

export type FilterKey =
  | "all"
  | "covered"
  | "partial"
  | "missing"
  | "na"
  | "errors"
  | "overridden";

/** Bucket an effective score into a filter/status group. null = judge error. */
export function bucketOf(
  score: number | null,
  corrected: boolean,
): FilterKey {
  if (corrected) return "overridden";
  if (score === null) return "errors";
  if (score === 0) return "na";
  if (score === 1) return "missing";
  if (score <= 3) return "partial";
  return "covered";
}

const LETTER = "abcdefgh";

function elementLabel(el: ElementJudgment, i: number): string {
  const name = el.id.replace(/_/g, " ");
  return `${LETTER[i] ?? i + 1}) ${name}`;
}

export function FindingsTable({
  findings,
  titles,
  correctionsByDisclosure,
  expandedId,
  onToggle,
  onCorrect,
  onTrace,
}: {
  findings: FindingView[];
  titles: Map<string, string>;
  correctionsByDisclosure: Record<string, CorrectionView>;
  expandedId: string | null;
  onToggle: (id: string) => void;
  onCorrect: (f: FindingView) => void;
  onTrace: (f: FindingView) => void;
}) {
  return (
    // Mobile: natural height — the page scrolls. md+: bounded inner scroller.
    <div className="rounded-3xl bg-surface md:min-h-0 md:flex-1 md:overflow-auto">
      <div className="md:min-w-[640px]">
      <div className="sticky top-0 z-10 hidden h-[38px] items-center bg-soft-2 px-4 text-xs font-medium text-muted-ink md:flex">
        <span className="w-11 shrink-0">Score</span>
        <span className="w-[110px] shrink-0">Disclosure</span>
        <span className="min-w-0 flex-1">Title</span>
        <span className="w-[70px] shrink-0">Elements</span>
        <span className="w-24 shrink-0">Status</span>
        <span className="w-14 shrink-0">p.</span>
        <span className="w-[72px] shrink-0" />
      </div>
      <div role="list">
        {findings.map((f) => {
          const correction = correctionsByDisclosure[f.disclosure_id];
          const open = expandedId === f.disclosure_id;
          const detailId = `finding-${f.disclosure_id.replace(/[^\w-]/g, "_")}-detail`;
          return (
            <div
              key={f.disclosure_id}
              role="listitem"
              className="border-b border-line last:border-0"
            >
              <Row
                finding={f}
                title={titles.get(f.disclosure_id)}
                correction={correction}
                open={open}
                detailId={detailId}
                onToggle={() => onToggle(f.disclosure_id)}
              />
              <MobileRow
                finding={f}
                title={titles.get(f.disclosure_id)}
                correction={correction}
                open={open}
                detailId={detailId}
                onToggle={() => onToggle(f.disclosure_id)}
              />
              {open && (
                <ExpandedDetail
                  finding={f}
                  correction={correction}
                  id={detailId}
                  onCorrect={() => onCorrect(f)}
                  onTrace={() => onTrace(f)}
                />
              )}
            </div>
          );
        })}
      </div>
      {findings.length === 0 && (
        <div className="grid h-40 place-items-center text-[13px] text-muted-ink">
          No findings match this filter.
        </div>
      )}
      </div>
    </div>
  );
}

function Row({
  finding: f,
  title,
  correction,
  open,
  detailId,
  onToggle,
}: {
  finding: FindingView;
  title?: string;
  correction?: CorrectionView;
  open: boolean;
  detailId: string;
  onToggle: () => void;
}) {
  const { score, corrected } = effectiveGrade(f.score, correction);
  const elements = correction?.corrected_elements ?? f.elements;
  const found = elements.filter((e) => e.status === "found").length;
  const bucket = bucketOf(score, corrected);
  const status: DisclosureStatus =
    bucket === "covered"
      ? "covered"
      : bucket === "partial"
        ? "partial"
        : bucket === "missing" || bucket === "na"
          ? "missing"
          : "error";

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={detailId}
      className={cn(
        "hidden h-[50px] w-full items-center px-4 text-left transition-colors hover:bg-soft/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50 md:flex",
        open && "bg-soft-2",
      )}
    >
      <span className="w-11 shrink-0">
        <ScorePill score={f.status === "error" ? null : score} />
      </span>
      <span className="w-[110px] shrink-0 truncate text-[13px] font-semibold text-ink">
        {f.disclosure_id}
      </span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
        {title ?? "—"}
      </span>
      <span className="w-[70px] shrink-0 text-[13px] tabular-nums text-muted-ink">
        {elements.length > 0 ? `${found}/${elements.length}` : "—"}
      </span>
      <span className="w-24 shrink-0">
        <StatusCell corrected={corrected} bucket={bucket} status={status} />
      </span>
      <span className="w-14 shrink-0 text-[13px] tabular-nums text-muted-ink">
        {f.evidence_page ?? "—"}
      </span>
      <span className="flex w-[72px] shrink-0 items-center justify-end gap-1.5 text-muted-ink">
        {open ? (
          <ChevronUp className="size-4" aria-hidden />
        ) : (
          <ChevronDown className="size-4" aria-hidden />
        )}
      </span>
    </button>
  );
}

function StatusCell({
  corrected,
  bucket,
  status,
}: {
  corrected: boolean;
  bucket: FilterKey;
  status: DisclosureStatus;
}) {
  if (corrected) return <Chip tone="accent">Overridden</Chip>;
  if (bucket === "na") return <Chip>N/A</Chip>;
  return <DisclosureStatusChip status={status} />;
}

/** Compact stacked row for phones — the 640px table isn't readable there. */
function MobileRow({
  finding: f,
  title,
  correction,
  open,
  detailId,
  onToggle,
}: {
  finding: FindingView;
  title?: string;
  correction?: CorrectionView;
  open: boolean;
  detailId: string;
  onToggle: () => void;
}) {
  const { score, corrected } = effectiveGrade(f.score, correction);
  const elements = correction?.corrected_elements ?? f.elements;
  const found = elements.filter((e) => e.status === "found").length;
  const bucket = bucketOf(score, corrected);
  const status: DisclosureStatus =
    bucket === "covered"
      ? "covered"
      : bucket === "partial"
        ? "partial"
        : bucket === "missing" || bucket === "na"
          ? "missing"
          : "error";

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={detailId}
      className={cn(
        "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-soft/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50 md:hidden",
        open && "bg-soft-2",
      )}
    >
      <span className="flex items-center gap-2.5">
        <ScorePill score={f.status === "error" ? null : score} />
        <span className="text-[13px] font-semibold text-ink">
          {f.disclosure_id}
        </span>
        <span className="min-w-0 flex-1" />
        <StatusCell corrected={corrected} bucket={bucket} status={status} />
        {open ? (
          <ChevronUp className="size-4 shrink-0 text-muted-ink" aria-hidden />
        ) : (
          <ChevronDown className="size-4 shrink-0 text-muted-ink" aria-hidden />
        )}
      </span>
      <span className="truncate text-[13px] text-ink">{title ?? "—"}</span>
      <span className="text-[11px] text-muted-ink">
        {elements.length > 0
          ? `${found} of ${elements.length} elements`
          : "No element breakdown"}
        {f.evidence_page != null && ` · evidence p.${f.evidence_page}`}
      </span>
    </button>
  );
}

function ExpandedDetail({
  finding: f,
  correction,
  id,
  onCorrect,
  onTrace,
}: {
  finding: FindingView;
  correction?: CorrectionView;
  id: string;
  onCorrect: () => void;
  onTrace: () => void;
}) {
  const { openEvidence } = useEvidenceViewer();
  const elements = correction?.corrected_elements ?? f.elements;
  const found = elements.filter((e) => e.status === "found").length;

  return (
    <div
      id={id}
      className="flex flex-col items-start gap-6 bg-soft-2 px-5 pb-5 pt-4 md:flex-row"
    >
      {/* Required elements */}
      <div className="flex w-full shrink-0 flex-col gap-1.5 md:w-80">
        <span className="text-[11px] font-semibold text-muted-ink">
          Required elements — {found} of {elements.length} found
        </span>
        {elements.map((el, i) => (
          <div key={el.id} className="flex items-center gap-2">
            <ElementIcon status={el.status} />
            <span className="min-w-0 flex-1 truncate text-xs text-ink">
              {elementLabel(el, i)}
            </span>
            {el.page != null && (
              <span className="text-[11px] text-muted-ink">p.{el.page}</span>
            )}
          </div>
        ))}
        {elements.length === 0 && (
          <span className="text-xs text-muted-ink">
            No element breakdown for this disclosure.
          </span>
        )}
      </div>

      {/* Evidence */}
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-[11px] font-semibold text-muted-ink">
          Evidence
        </span>
        {f.evidence_excerpt ? (
          <div className="flex flex-col gap-2 bg-surface p-3">
            <p className="text-xs/[18px] italic text-ink">
              “{f.evidence_excerpt}”
            </p>
          </div>
        ) : (
          <p className="text-xs text-muted-ink">
            {f.status === "error"
              ? "Judging failed — see the trace for details."
              : "No supporting passage was found in the report."}
          </p>
        )}
        {f.evidence_page != null && (
          <span className="text-[11px] text-muted-ink">
            p. {f.evidence_page} · evidence excerpt
          </span>
        )}
        {f.evidence_page != null && (
          <Button
            variant="outline"
            size="sm"
            icon={<FileText />}
            className="w-fit"
            onClick={() => openEvidence(f)}
          >
            Open evidence
          </Button>
        )}
      </div>

      {/* Assessment + fix + actions */}
      <div className="flex w-full shrink-0 flex-col gap-1.5 md:w-[300px]">
        <span className="text-[11px] font-semibold text-muted-ink">
          Assessment
        </span>
        <p className="text-xs/[17px] text-ink">
          {f.na_reason ? `Not applicable — ${f.na_reason}` : f.note}
        </p>
        {correction && (
          <p className="text-xs/[17px] text-muted-ink">
            Corrected to {correction.corrected_score}/5 by {correction.reviewer}
            {correction.rationale ? ` — ${correction.rationale}` : ""}
          </p>
        )}
        {f.suggested_fix && (
          <>
            <span className="pt-1 text-[11px] font-semibold text-muted-ink">
              Suggested fix
            </span>
            <p className="text-xs/[17px] text-muted-ink">{f.suggested_fix}</p>
          </>
        )}
        <div className="flex gap-2 pt-1.5">
          <Button size="sm" icon={<PenLine />} onClick={onCorrect}>
            Correct
          </Button>
          <Button
            variant="outline"
            size="sm"
            icon={<Terminal />}
            onClick={onTrace}
          >
            Trace
          </Button>
        </div>
      </div>
    </div>
  );
}

function ElementIcon({ status }: { status: ElementJudgment["status"] }) {
  const Icon =
    status === "found" ? Check : status === "partial" ? Minus : X;
  return (
    <Icon
      className={cn(
        "size-3.5 shrink-0",
        status === "found" && "text-success",
        status === "partial" && "text-warning",
        status === "missing" && "text-danger",
      )}
      role="img"
      aria-label={status}
    />
  );
}
