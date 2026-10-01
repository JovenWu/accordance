import { DisclosureStatusChip, ScorePill } from "@/components/ui/chip";
import type { FindingView } from "@/types";

/** One judged finding in the live/failed stream — score pill, id + title,
 * element progress meta, status chip. */
export function FeedRow({
  finding,
  title,
}: {
  finding: FindingView;
  title?: string;
}) {
  const found = finding.elements.filter((e) => e.status === "found").length;
  const meta = finding.na_reason
    ? `N/A · ${finding.na_reason}`
    : [
        `${found} of ${finding.elements.length} elements`,
        finding.evidence_page != null && `evidence p.${finding.evidence_page}`,
        finding.vision_fallback_used && "vision fallback used",
      ]
        .filter(Boolean)
        .join(" · ");

  return (
    <div className="flex h-[52px] w-full shrink-0 items-center gap-3.5 px-4">
      <ScorePill score={finding.score} />
      <div className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-[13px] font-medium text-ink">
          {finding.disclosure_id}
          {title ? ` — ${title}` : ""}
        </span>
        <span className="truncate text-[11px] text-muted-ink">{meta}</span>
      </div>
      <DisclosureStatusChip status={finding.status} na={finding.score === 0} />
    </div>
  );
}
