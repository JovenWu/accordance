import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import { SearchInput } from "@/components/ui/input";
import { useModalA11y } from "@/lib/useModalA11y";
import { cn } from "@/lib/utils";
import {
  allIds,
  disclosureVisible,
  groupByCategory,
  standardState,
  toggleDisclosure,
  toggleStandard,
} from "@/lib/selection";
import type { KbStandard, Preset } from "@/types";

function groupLabel(standard: string): string {
  // "GRI 2: General Disclosures 2021" → "GRI 2 · General Disclosures 2021"
  return standard.replace(/:\s*/, " · ");
}

export function ScopeModal({
  open,
  onClose,
  groups,
  presets,
  selected,
  locked,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  groups: KbStandard[];
  presets: Preset[];
  selected: Set<string>;
  /** Already-judged ids (judge-more) — shown checked + disabled. */
  locked?: Set<string>;
  onApply: (next: Set<string>) => void;
}) {
  const panelRef = useModalA11y<HTMLDivElement>(open, onClose);
  const [draft, setDraft] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [currentOnly, setCurrentOnly] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const lockedSet = useMemo(() => locked ?? new Set<string>(), [locked]);

  // Fresh draft each time the modal opens.
  useEffect(() => {
    if (open) {
      setDraft(new Set(selected));
      setQuery("");
      setCollapsed(new Set());
    }
  }, [open, selected]);

  const total = useMemo(() => allIds(groups).length, [groups]);
  const categories = useMemo(() => groupByCategory(groups), [groups]);

  const visibleGroups = useMemo(() => {
    const opts = { query, currentOnly, selected: draft };
    return groups
      .map((g) => ({
        ...g,
        disclosures: g.disclosures.filter((d) =>
          disclosureVisible(d, g.standard, opts),
        ),
      }))
      .filter((g) => g.disclosures.length > 0);
  }, [groups, query, currentOnly, draft]);

  function applyPreset(p: Preset | null) {
    setDraft(p ? new Set(p.disclosure_ids) : new Set(allIds(groups)));
  }

  if (!open) return null;

  // A pill is "active" when the draft exactly matches its id set — so manual
  // edits deselect the pill instead of lying about what it represents.
  const sameSet = (ids: string[]) =>
    ids.length === draft.size && ids.every((id) => draft.has(id));
  const presetPills = [
    { id: "all", name: "All GRI", ids: allIds(groups), active: sameSet(allIds(groups)) },
    ...presets.map((p) => ({
      id: p.id,
      name: p.name,
      ids: p.disclosure_ids,
      active: sameSet(p.disclosure_ids),
    })),
  ];

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-dim-deep p-4 animate-in fade-in-0 [--tw-duration:150ms]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Choose analysis scope"
        tabIndex={-1}
        className="flex w-full max-w-[94vw] max-h-[90vh] flex-col gap-4 rounded-3xl bg-surface p-6 shadow-modal outline-none animate-in fade-in-0 zoom-in-95 [--tw-duration:150ms] sm:w-[680px] sm:max-h-[86vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-1">
            <h2 className="text-base font-medium text-ink">
              Choose analysis scope
            </h2>
            <p className="text-[13px] text-muted-ink">
              Select the GRI disclosures the judge evaluates for this run.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid size-6 shrink-0 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-ink">
            Sector preset
          </span>
          <div className="flex flex-wrap gap-2">
            {presetPills.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() =>
                  applyPreset(
                    p.id === "all"
                      ? null
                      : (presets.find((x) => x.id === p.id) ?? null),
                  )
                }
                className={cn(
                  "rounded-2xl px-2 py-0.5 text-xs font-medium transition-colors",
                  p.active
                    ? "bg-accent text-accent-ink"
                    : "bg-soft text-ink hover:bg-soft-2",
                )}
              >
                {p.name} · {p.ids.length}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <SearchInput
            className="min-w-0 flex-1 basis-48"
            inputProps={{
              placeholder: "Search disclosures — e.g. emissions, water, 305",
              value: query,
              onChange: (e) => setQuery(e.target.value),
            }}
          />
          <label className="flex shrink-0 items-center gap-2 text-xs text-muted-ink">
            <Checkbox
              checked={currentOnly}
              onCheckedChange={(v) => setCurrentOnly(v)}
              aria-label="Current editions only"
            />
            Current editions only
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-line">
          {categories.map((cat) =>
            cat.standards
              .map((g) => visibleGroups.find((v) => v.standard === g.standard))
              .filter((g): g is KbStandard => !!g)
              .map((g) => {
                const state = standardState(g, draft, lockedSet);
                const isCollapsed = collapsed.has(g.standard);
                const visibleIds = g.disclosures.map((d) => d.id);
                const selCount = visibleIds.filter(
                  (id) => draft.has(id) || lockedSet.has(id),
                ).length;
                return (
                  <div key={g.standard}>
                    <div className="flex h-11 items-center gap-2.5 px-3.5">
                      <Checkbox
                        checked={state === "checked"}
                        indeterminate={state === "indeterminate"}
                        aria-label={`Toggle ${g.standard}`}
                        onCheckedChange={() =>
                          setDraft(toggleStandard(g, draft, lockedSet))
                        }
                      />
                      <button
                        type="button"
                        aria-label={
                          isCollapsed
                            ? `Expand ${g.standard}`
                            : `Collapse ${g.standard}`
                        }
                        aria-expanded={!isCollapsed}
                        onClick={() =>
                          setCollapsed((cur) => {
                            const next = new Set(cur);
                            if (next.has(g.standard)) next.delete(g.standard);
                            else next.add(g.standard);
                            return next;
                          })
                        }
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        {isCollapsed ? (
                          <ChevronRight className="size-4 shrink-0 text-muted-ink" aria-hidden />
                        ) : (
                          <ChevronDown className="size-4 shrink-0 text-muted-ink" aria-hidden />
                        )}
                        <span className="flex-1 truncate text-[13px] font-medium text-ink">
                          {groupLabel(g.standard)}
                        </span>
                      </button>
                      <span className="text-xs tabular-nums text-muted-ink">
                        {selCount}/{g.disclosures.length}
                      </span>
                    </div>
                    {!isCollapsed &&
                      g.disclosures.map((d) => {
                        const isLocked = lockedSet.has(d.id);
                        const on = isLocked || draft.has(d.id);
                        return (
                          <div key={d.id} className="border-t border-line">
                            <div className="flex h-9 items-center gap-2.5 pl-11 pr-3.5">
                              <Checkbox
                                checked={on}
                                disabled={isLocked}
                                aria-label={d.id}
                                onCheckedChange={() =>
                                  setDraft(toggleDisclosure(draft, d.id))
                                }
                              />
                              <span className="flex-1 truncate text-[13px] text-ink">
                                {d.id} {d.title}
                              </span>
                              {d.status !== "current" && (
                                <Chip className="px-1.5 py-px text-[11px]">
                                  {d.status}
                                </Chip>
                              )}
                              {isLocked && (
                                <Chip
                                  tone="accent"
                                  className="px-1.5 py-px text-[11px]"
                                >
                                  judged
                                </Chip>
                              )}
                            </div>
                          </div>
                        );
                      })}
                  </div>
                );
              }),
          )}
          {visibleGroups.length === 0 && (
            <p className="p-6 text-center text-[13px] text-muted-ink">
              No disclosures match your search.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="flex items-center gap-3.5">
            <span className="text-[13px] tabular-nums text-muted-ink">
              {draft.size} of {total} selected
            </span>
            <button
              type="button"
              className="text-[13px] font-medium text-accent hover:underline"
              onClick={() =>
                setDraft(
                  new Set(allIds(groups).filter((id) => !lockedSet.has(id))),
                )
              }
            >
              Select all
            </button>
            <button
              type="button"
              className="text-[13px] font-medium text-muted-ink hover:underline"
              onClick={() => setDraft(new Set())}
            >
              Clear
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="flat" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={draft.size === 0}
              onClick={() => {
                onApply(draft);
                onClose();
              }}
            >
              <Check aria-hidden />
              Use scope
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
