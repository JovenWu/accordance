import { useEffect, useMemo, useState } from "react";
import { Download, X } from "lucide-react";

import { downloadFile, exportSelectedCoverageUrl, getExportOptions } from "@/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Select } from "@/components/ui/input";
import { useModalA11y } from "@/lib/useModalA11y";
import { useToast } from "@/components/ui/toast";
import type { ReportExportOption } from "@/types";

/**
 * Coverage-matrix export. Rows are reports with ≥1 completed run; the version
 * picker chooses which run contributes its column, or "all" for every
 * completed version of that report.
 */
export function ExportDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const panelRef = useModalA11y<HTMLDivElement>(open, onClose);
  const [options, setOptions] = useState<ReportExportOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // report_id → run_id | "all": the version that report contributes when its
  // checkbox is on (the picker always shows a version, included or not).
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [included, setIncluded] = useState<ReadonlySet<string>>(new Set());
  const { toast } = useToast();

  useEffect(() => {
    if (!open) return;
    setOptions(null);
    setError(null);
    setIncluded(new Set());
    getExportOptions()
      .then((opts) => {
        setOptions(opts);
        // Picker default: each report's latest completed version.
        setPicked(
          Object.fromEntries(opts.map((o) => [o.report_id, o.versions[0].run_id])),
        );
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, [open]);

  const selectedRunIds = useMemo(() => {
    if (!options) return [];
    const ids: string[] = [];
    for (const o of options) {
      if (!included.has(o.report_id)) continue;
      const v = picked[o.report_id];
      if (v === "all") ids.push(...o.versions.map((x) => x.run_id));
      else if (v) ids.push(v);
    }
    return ids;
  }, [options, picked, included]);

  const reportCount = included.size;

  function download() {
    if (selectedRunIds.length === 0) return;
    downloadFile(exportSelectedCoverageUrl(selectedRunIds));
    toast({
      title: "Export started",
      message: `${reportCount} report${reportCount === 1 ? "" : "s"} · ${selectedRunIds.length} run${selectedRunIds.length === 1 ? "" : "s"}`,
    });
    onClose();
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-dim-deep p-4 animate-in fade-in-0 [--tw-duration:150ms]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Export coverage"
        tabIndex={-1}
        className="relative flex w-full max-w-[94vw] flex-col gap-4 rounded-3xl bg-surface p-6 shadow-modal outline-none max-h-[90vh] overflow-y-auto animate-in fade-in-0 zoom-in-95 [--tw-duration:150ms] sm:w-[580px]"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="absolute right-6 top-[22px] grid size-6 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2"
        >
          <X className="size-3.5" aria-hidden />
        </button>

        <div className="flex flex-col gap-1">
          <h2 className="text-base font-medium text-ink">Export coverage</h2>
          <p className="text-xs text-muted-ink">
            Build an XLSX coverage matrix from selected runs. Corrections are
            included in effective scores.
          </p>
        </div>

        <div className="max-h-[340px] overflow-y-auto rounded-xl border border-line">
          {options === null && !error && (
            <p className="p-6 text-center text-[13px] text-muted-ink">
              Loading exportable reports…
            </p>
          )}
          {error && (
            <p role="alert" className="p-6 text-center text-[13px] text-danger">
              {error}
            </p>
          )}
          {options?.length === 0 && (
            <p className="p-6 text-center text-[13px] text-muted-ink">
              No completed runs yet — finish an analysis to export coverage.
            </p>
          )}
          {options?.map((o) => (
            <label
              key={o.report_id}
              className="flex h-12 cursor-pointer items-center gap-2.5 border-b border-line px-3.5 last:border-b-0"
            >
              <Checkbox
                checked={included.has(o.report_id)}
                onCheckedChange={(v) =>
                  setIncluded((cur) => {
                    const next = new Set(cur);
                    if (v) next.add(o.report_id);
                    else next.delete(o.report_id);
                    return next;
                  })
                }
                aria-label={`Include ${o.name}`}
              />
              <span className="flex-1 truncate text-[13px] font-medium text-ink">
                {o.name}
              </span>
              <Select
                className="w-[140px] shrink-0 sm:w-[170px]"
                value={picked[o.report_id] ?? o.versions[0].run_id}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) =>
                  setPicked((cur) => ({ ...cur, [o.report_id]: e.target.value }))
                }
                aria-label={`Version for ${o.name}`}
              >
                {o.versions.map((v, i) => (
                  <option key={v.run_id} value={v.run_id}>
                    v{v.version_number}
                    {i === 0 ? " · latest" : ""}
                  </option>
                ))}
                {o.versions.length > 1 && (
                  <option value="all">All {o.versions.length} versions</option>
                )}
              </Select>
            </label>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 pt-1">
          <span className="text-xs text-muted-ink">
            {reportCount} report{reportCount === 1 ? "" : "s"} ·{" "}
            {selectedRunIds.length} run{selectedRunIds.length === 1 ? "" : "s"}{" "}
            selected
          </span>
          <div className="flex items-center gap-2">
            <Button variant="flat" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={download}
              disabled={selectedRunIds.length === 0}
            >
              <Download aria-hidden />
              Download XLSX
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
