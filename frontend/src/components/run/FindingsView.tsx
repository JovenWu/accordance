import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { useKbTitles } from "@/lib/useKbTitles";
import { scoreMeta } from "@/lib/score";
import { cn } from "@/lib/utils";
import {
  bucketOf,
  FindingsTable,
  type FilterKey,
} from "./FindingsTable";
import { CorrectionsDrawer } from "./CorrectionsDrawer";
import type { CorrectionView, FindingView, RunDetail } from "@/types";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "covered", label: "Covered" },
  { key: "partial", label: "Partial" },
  { key: "missing", label: "Missing" },
  { key: "na", label: "N/A" },
  { key: "errors", label: "Errors" },
  { key: "overridden", label: "Overridden" },
];

const BAR_TONE: Record<number, string> = {
  5: "bg-success",
  4: "bg-success",
  3: "bg-warning",
  2: "bg-warning",
  1: "bg-danger",
  0: "bg-muted-ink",
};

export function FindingsView({
  run,
  onChanged,
  onCorrect,
  onTrace,
}: {
  run: RunDetail;
  onChanged: () => void;
  onCorrect: (f: FindingView) => void;
  onTrace: (f: FindingView) => void;
}) {
  const titles = useKbTitles();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [query, setQuery] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [correctionsOpen, setCorrectionsOpen] = useState(false);

  const correctionsByDisclosure = useMemo(() => {
    const m: Record<string, CorrectionView> = {};
    for (const c of run.corrections) m[c.disclosure_id] = c;
    return m;
  }, [run.corrections]);

  // Effective score = correction when present, else agent score.
  const effective = useMemo(
    () =>
      run.findings.map((f) => {
        const c = correctionsByDisclosure[f.disclosure_id];
        return {
          f,
          score: c ? c.corrected_score : f.score,
          corrected: !!c,
        };
      }),
    [run.findings, correctionsByDisclosure],
  );

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = {
      all: effective.length,
      covered: 0,
      partial: 0,
      missing: 0,
      na: 0,
      errors: 0,
      overridden: 0,
    };
    for (const e of effective) {
      if (e.corrected) c.overridden += 1;
      else c[bucketOf(e.score, false)] += 1;
    }
    return c;
  }, [effective]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return effective
      .filter((e) =>
        filter === "all"
          ? true
          : filter === "overridden"
            ? e.corrected
            : !e.corrected && bucketOf(e.score, false) === filter,
      )
      .filter(
        (e) =>
          !q ||
          e.f.disclosure_id.toLowerCase().includes(q) ||
          (titles.get(e.f.disclosure_id) ?? "").toLowerCase().includes(q) ||
          e.f.note.toLowerCase().includes(q),
      )
      .map((e) => e.f);
  }, [effective, filter, query, titles]);

  const dist = useMemo(() => {
    const d = [0, 0, 0, 0, 0, 0] as number[]; // index = score
    let errors = 0;
    for (const e of effective) {
      if (e.score === null) errors += 1;
      else d[e.score] += 1;
    }
    return { d, errors };
  }, [effective]);

  const avg = useMemo(() => {
    const scored = effective.filter((e) => e.score !== null && e.score > 0);
    if (scored.length === 0) return null;
    return (
      scored.reduce((s, e) => s + (e.score as number), 0) / scored.length
    ).toFixed(1);
  }, [effective]);

  const reviewers = useMemo(
    () => [...new Set(run.corrections.map((c) => c.reviewer))].join(", "),
    [run.corrections],
  );

  return (
    <>
      <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-start">
        {/* Grade distribution */}
        <div className="flex flex-1 flex-col gap-2.5 rounded-3xl bg-surface p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-ink">
              Grade distribution
            </span>
            <span className="text-xs font-medium text-ink">
              {avg !== null ? `avg ${avg} / 5` : "—"}
            </span>
          </div>
          {/* The legend below repeats every count as text — the colored bar
              itself is decorative, so it's hidden from assistive tech. */}
          <div
            aria-hidden
            className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-[5px]"
          >
            {[5, 4, 3, 2, 1, 0].map(
              (s) =>
                dist.d[s] > 0 && (
                  <div
                    key={s}
                    className={BAR_TONE[s]}
                    style={{ flex: dist.d[s] }}
                  />
                ),
            )}
            {dist.errors > 0 && (
              <div className="bg-danger" style={{ flex: dist.errors }} />
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3.5">
            {[5, 4, 3, 2, 1, 0].map(
              (s) =>
                dist.d[s] > 0 && (
                  <span
                    key={s}
                    className="flex items-center gap-1.5 text-[11px] text-muted-ink"
                  >
                    <i
                      className={cn(
                        "size-2 shrink-0 rounded-[2px]",
                        BAR_TONE[s],
                      )}
                    />
                    {s} · {scoreMeta(s).label} {dist.d[s]}
                  </span>
                ),
            )}
            {dist.errors > 0 && (
              <span className="flex items-center gap-1.5 text-[11px] text-muted-ink">
                <i className="size-2 shrink-0 rounded-[2px] bg-danger" />
                Errors {dist.errors}
              </span>
            )}
          </div>
        </div>
        {/* Human review */}
        <button
          type="button"
          onClick={() => setCorrectionsOpen(true)}
          className="flex w-full shrink-0 flex-col gap-1 rounded-3xl bg-surface p-4 text-left transition-colors hover:bg-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 sm:w-[280px]"
        >
          <span className="text-xs font-medium text-muted-ink">
            Human review
          </span>
          <span className="text-[20px] font-semibold text-ink">
            {run.corrections.length}{" "}
            {run.corrections.length === 1 ? "correction" : "corrections"}
          </span>
          <span className="text-[11px] text-muted-ink">
            {run.corrections.length > 0
              ? `by ${reviewers} · included in exports`
              : "Expand a finding to correct it"}
          </span>
        </button>
      </div>

      {/* Filters + search */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {FILTERS.map(
            ({ key, label }) =>
              (key === "all" || counts[key] > 0) && (
                <button
                  key={key}
                  type="button"
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                  className={cn(
                    "rounded-2xl px-2 py-0.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                    filter === key
                      ? "bg-accent text-accent-ink"
                      : "bg-soft-2 text-ink hover:bg-soft",
                  )}
                >
                  {label} · {counts[key]}
                </button>
              ),
          )}
        </div>
        <label className="flex h-9 w-full shrink-0 items-center gap-1.5 rounded-xl bg-surface px-3 shadow-[0_1px_2px_#0000000F] focus-within:ring-2 focus-within:ring-accent/40 sm:w-[220px]">
          <Search className="size-4 text-muted-ink" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter findings…"
            aria-label="Filter findings"
            className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted-ink focus-visible:outline-none"
          />
        </label>
      </div>

      <FindingsTable
        findings={visible}
        titles={titles}
        correctionsByDisclosure={correctionsByDisclosure}
        expandedId={expandedId}
        onToggle={(id) => setExpandedId((cur) => (cur === id ? null : id))}
        onCorrect={onCorrect}
        onTrace={onTrace}
      />

      {correctionsOpen && (
        <CorrectionsDrawer
          run={run}
          titles={titles}
          onClose={() => setCorrectionsOpen(false)}
          onChanged={onChanged}
        />
      )}
    </>
  );
}
