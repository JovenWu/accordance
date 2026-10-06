import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowLeftRight } from "lucide-react";

import { compare, getReport, isNotFound } from "@/api";
import { Button } from "@/components/ui/button";
import { Chip, ScorePill } from "@/components/ui/chip";
import { Select } from "@/components/ui/input";
import { useKbTitles } from "@/lib/useKbTitles";
import { formatDateTime } from "@/lib/datetime";
import { cn } from "@/lib/utils";
import { NotFoundPage } from "@/pages/NotFoundPage";
import type {
  CompareResponse,
  DiffEntry,
  ReportDetail,
  VersionSummary,
} from "@/types";

type Category = "improved" | "regressed" | "added" | "removed" | "unchanged";
type Filter = "changed" | Category;

const CATEGORY_META: Record<
  Category,
  { label: string; tone: "success" | "danger" | "accent" | "neutral" }
> = {
  improved: { label: "Improved", tone: "success" },
  regressed: { label: "Regressed", tone: "danger" },
  added: { label: "Added", tone: "accent" },
  removed: { label: "Removed", tone: "neutral" },
  unchanged: { label: "Unchanged", tone: "neutral" },
};

function categoryOf(d: DiffEntry): Category {
  if (d.change === "only_in_b") return "added";
  if (d.change === "only_in_a") return "removed";
  if (d.change === "unchanged" || d.change === "both_missing")
    return "unchanged";
  const as = d.a?.score ?? 0;
  const bs = d.b?.score ?? 0;
  if (bs > as) return "improved";
  if (bs < as) return "regressed";
  return "unchanged";
}

function noteOf(d: DiffEntry): string {
  switch (d.change) {
    case "only_in_b":
      return "newly judged in this version";
    case "only_in_a":
      return "dropped from scope";
    case "both_missing":
      return "missing in both versions";
    case "unchanged":
      return d.a?.status === "missing" ? "missing in both versions" : "—";
    default: {
      const ea = d.a?.elements?.filter((e) => e.status === "found").length ?? 0;
      const eb = d.b?.elements?.filter((e) => e.status === "found").length ?? 0;
      const diff = eb - ea;
      if (diff > 0) return `${diff} more elements found`;
      if (diff < 0) return `${-diff} fewer elements found`;
      return d.change === "note_changed" ? "assessment updated" : "—";
    }
  }
}

const FILTERS: { key: Filter; label: string }[] = [
  { key: "changed", label: "Changed" },
  { key: "improved", label: "Improved" },
  { key: "regressed", label: "Regressed" },
  { key: "added", label: "Added" },
  { key: "removed", label: "Removed" },
  { key: "unchanged", label: "Unchanged" },
];

function versionLabel(v: VersionSummary): string {
  return `v${v.version_number} — ${formatDateTime(v.uploaded_at, {
    month: "short",
    day: "numeric",
  })}`;
}

export function ComparePage() {
  const { reportId } = useParams<{ reportId: string }>();
  const [params, setParams] = useSearchParams();
  const titles = useKbTitles();
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [data, setData] = useState<CompareResponse | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("changed");

  const a = params.get("a");
  const b = params.get("b");

  useEffect(() => {
    if (!reportId) return;
    getReport(reportId)
      .then((r) => {
        setReport(r);
        if (!a || !b) {
          const sorted = [...r.runs].sort(
            (x, y) => y.version_number - x.version_number,
          );
          if (sorted.length >= 2) {
            setParams(
              { a: sorted[1].run_id, b: sorted[0].run_id },
              { replace: true },
            );
          }
        }
      })
      .catch((e) =>
        isNotFound(e)
          ? setMissing(true)
          : setError(e instanceof Error ? e.message : String(e)),
      );
  }, [reportId, a, b, setParams]);

  useEffect(() => {
    if (!reportId || !a || !b) return;
    setData(null);
    setError(null);
    compare(reportId, a, b)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [reportId, a, b]);

  const rows = useMemo(
    () =>
      (data?.diff ?? []).map((d) => ({ d, cat: categoryOf(d) })),
    [data],
  );
  const counts = useMemo(() => {
    const c: Record<Filter, number> = {
      changed: 0,
      improved: 0,
      regressed: 0,
      added: 0,
      removed: 0,
      unchanged: 0,
    };
    for (const r of rows) {
      c[r.cat] += 1;
      if (r.cat !== "unchanged") c.changed += 1;
    }
    return c;
  }, [rows]);
  const visible = rows.filter((r) =>
    filter === "changed" ? r.cat !== "unchanged" : r.cat === filter,
  );

  function pick(side: "a" | "b", runId: string) {
    const next = new URLSearchParams(params);
    next.set(side, runId);
    setParams(next);
  }
  function swap() {
    if (!a || !b) return;
    setParams({ a: b, b: a });
  }

  if (missing) return <NotFoundPage title="Report not found" />;

  const deltas: { key: keyof CompareResponse["summary_delta"]; label: string }[] =
    [
      { key: "covered", label: "Covered" },
      { key: "partial", label: "Partial" },
      { key: "missing", label: "Missing" },
    ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <Link
        to={`/reports/${reportId}`}
        className="flex w-fit items-center gap-1.5 text-[13px] text-muted-ink hover:text-ink"
      >
        <ArrowLeft className="size-4" aria-hidden />
        <span className="font-medium">{report?.name ?? "Report"}</span>
        <span>/ Compare versions</span>
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <h1 className="text-[20px] font-semibold text-ink">
          Compare versions
        </h1>
        <div className="flex w-full flex-col items-stretch gap-2.5 sm:w-auto sm:flex-row sm:items-end">
          <label className="flex w-full flex-col gap-1 sm:w-[200px]">
            <span className="text-xs font-medium text-ink">Version A</span>
            <Select
              value={a ?? ""}
              onChange={(e) => pick("a", e.target.value)}
            >
              {report?.runs.map((v) => (
                <option key={v.run_id} value={v.run_id}>
                  {versionLabel(v)}
                </option>
              ))}
            </Select>
          </label>
          <Button
            variant="flat"
            size="icon"
            aria-label="Swap versions"
            onClick={swap}
          >
            <ArrowLeftRight aria-hidden />
          </Button>
          <label className="flex w-full flex-col gap-1 sm:w-[200px]">
            <span className="text-xs font-medium text-ink">Version B</span>
            <Select
              value={b ?? ""}
              onChange={(e) => pick("b", e.target.value)}
            >
              {report?.runs.map((v) => (
                <option key={v.run_id} value={v.run_id}>
                  {versionLabel(v)}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}
      {!error && !data && (
        <p className="grid flex-1 place-items-center text-sm text-muted-ink">
          Loading comparison…
        </p>
      )}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {deltas.map(({ key, label }) => {
              const d = data.summary_delta[key];
              return (
                <div
                  key={key}
                  className="flex flex-1 flex-col gap-1 rounded-3xl bg-surface p-4"
                >
                  <span className="text-xs text-muted-ink">{label}</span>
                  <span className="flex items-center gap-2">
                    <span className="text-[20px] font-semibold tabular-nums text-ink">
                      {d.a} → {d.b}
                    </span>
                    <span
                      className={cn(
                        "text-xs font-semibold tabular-nums",
                        d.delta === 0 ? "text-muted-ink" : "text-success",
                      )}
                    >
                      {d.delta > 0 ? `+${d.delta}` : `−${-d.delta}`}
                    </span>
                  </span>
                </div>
              );
            })}
            <div className="flex flex-1 flex-col gap-1 rounded-3xl bg-surface p-4">
              <span className="text-xs text-muted-ink">Changed findings</span>
              <span className="flex items-center gap-2">
                <span className="text-[20px] font-semibold tabular-nums text-ink">
                  — → {counts.changed}
                </span>
                <span className="text-xs font-semibold text-muted-ink">
                  of {rows.length}
                </span>
              </span>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {FILTERS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setFilter(key)}
                className={cn(
                  "rounded-2xl px-2 py-0.5 text-xs font-medium transition-colors",
                  filter === key
                    ? "bg-accent text-accent-ink"
                    : "bg-soft-2 text-ink hover:bg-soft",
                )}
              >
                {label} · {counts[key]}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-auto rounded-3xl bg-surface">
            <div className="min-w-[720px]">
              <div className="sticky top-0 z-10 flex h-[38px] items-center bg-soft-2 px-4 text-xs font-medium text-muted-ink">
                <span className="w-[110px] shrink-0">Disclosure</span>
                <span className="min-w-0 flex-1">Title</span>
                <span className="w-16 shrink-0">
                  v{data.a.version_number}
                </span>
                <span className="w-16 shrink-0">
                  v{data.b.version_number}
                </span>
                <span className="w-[120px] shrink-0">Change</span>
                <span className="w-[200px] shrink-0">Note</span>
              </div>
              {visible.map(({ d, cat }) => (
                <div
                  key={d.disclosure_id}
                  className="flex h-12 items-center border-b border-line px-4 last:border-0"
                >
                  <span className="w-[110px] shrink-0 text-[13px] font-semibold text-ink">
                    {d.disclosure_id}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                    {titles.get(d.disclosure_id) ?? "—"}
                  </span>
                  <span className="w-16 shrink-0">
                    {d.a ? (
                      <ScorePill score={d.a.score} />
                    ) : (
                      <span className="text-[13px] text-muted-ink">—</span>
                    )}
                  </span>
                  <span className="w-16 shrink-0">
                    {d.b ? (
                      <ScorePill score={d.b.score} />
                    ) : (
                      <span className="text-[13px] text-muted-ink">—</span>
                    )}
                  </span>
                  <span className="flex w-[120px] shrink-0 items-center">
                    <Chip tone={CATEGORY_META[cat].tone}>
                      {CATEGORY_META[cat].label}
                    </Chip>
                  </span>
                  <span className="w-[200px] shrink-0 truncate text-xs text-muted-ink">
                    {noteOf(d)}
                  </span>
                </div>
              ))}
              {visible.length === 0 && (
                <p className="grid h-40 place-items-center text-[13px] text-muted-ink">
                  No matching rows.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
