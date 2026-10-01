import type { KbDisclosure, KbStandard } from "../types";

export type TriState = "checked" | "indeterminate" | "unchecked";

export function toggleDisclosure(selected: Set<string>, id: string): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

// Selectable (non-locked) disclosure ids across one or more standards. Locked
// (e.g. already-judged) disclosures are excluded so select-all / toggle actions
// only affect what the user can still change.
function selectableIds(
  standards: KbStandard[],
  locked: Set<string>,
): string[] {
  return standards
    .flatMap((s) => s.disclosures.map((d) => d.id))
    .filter((id) => !locked.has(id));
}

// Parent (standard/category) checkbox DISPLAY state: a child counts as "on"
// when it is locked (already judged) OR selected, so a fully-judged group reads
// as done (checked) rather than empty — consistent with how the judged child
// rows render. Toggling (toggle* below) still affects only selectable children.
function parentState(
  standards: KbStandard[],
  selected: Set<string>,
  locked: Set<string>,
): TriState {
  const ids = standards.flatMap((s) => s.disclosures.map((d) => d.id));
  if (ids.length === 0) return "unchecked";
  const on = ids.filter((id) => locked.has(id) || selected.has(id)).length;
  if (on === 0) return "unchecked";
  if (on === ids.length) return "checked";
  return "indeterminate";
}

// True when every disclosure in the group is locked (judged) — nothing left to
// toggle, so the parent checkbox is shown checked + disabled.
export function isFullyLocked(
  standards: KbStandard[],
  locked: Set<string>,
): boolean {
  const ids = standards.flatMap((s) => s.disclosures.map((d) => d.id));
  return ids.length > 0 && ids.every((id) => locked.has(id));
}

function toggleIds(
  ids: string[],
  selected: Set<string>,
): Set<string> {
  const next = new Set(selected);
  const allOn = ids.length > 0 && ids.every((id) => next.has(id));
  if (allOn) ids.forEach((id) => next.delete(id));
  else ids.forEach((id) => next.add(id));
  return next;
}

export function standardState(
  group: KbStandard,
  selected: Set<string>,
  locked: Set<string> = new Set(),
): TriState {
  return parentState([group], selected, locked);
}

export function toggleStandard(
  group: KbStandard,
  selected: Set<string>,
  locked: Set<string> = new Set(),
): Set<string> {
  return toggleIds(selectableIds([group], locked), selected);
}

export function categoryState(
  standards: KbStandard[],
  selected: Set<string>,
  locked: Set<string> = new Set(),
): TriState {
  return parentState(standards, selected, locked);
}

export function toggleCategory(
  standards: KbStandard[],
  selected: Set<string>,
  locked: Set<string> = new Set(),
): Set<string> {
  return toggleIds(selectableIds(standards, locked), selected);
}

export function allIds(groups: KbStandard[]): string[] {
  return groups.flatMap((g) => g.disclosures.map((d) => d.id));
}

/**
 * Map the compare selection (run ids) to {runId, versionNumber} chips, dropping
 * any id whose version is no longer present (e.g. deleted in another tab). This
 * replaces a `map().get(id)!` non-null assertion that threw — and, with no error
 * boundary, blanked the whole app — when a selected version vanished.
 */
export function compareSelectionChips(
  selected: string[],
  versionByRunId: Map<string, { version_number: number }>,
): { runId: string; versionNumber: number }[] {
  return selected.flatMap((id) => {
    const v = versionByRunId.get(id);
    return v ? [{ runId: id, versionNumber: v.version_number }] : [];
  });
}

export type Category = "universal" | "topic" | "management" | "sector";

const CATEGORY_ORDER: Category[] = [
  "universal",
  "topic",
  "management",
  "sector",
];
const CATEGORY_LABEL: Record<Category, string> = {
  universal: "Universal",
  topic: "Topic",
  management: "Management",
  sector: "Sector",
};

export interface CategoryGroup {
  category: Category | string;
  label: string;
  standards: KbStandard[];
}

/** A standard's category = the category of its disclosures (uniform per standard). */
export function categoryOf(group: KbStandard): Category | string {
  return group.disclosures[0]?.category ?? "topic";
}

/**
 * Bucket standards into category groups in display order (Universal → Topic →
 * Sector), preserving input order within each bucket. Empty categories are
 * omitted; any unknown category (not in CATEGORY_ORDER) is appended last.
 */
export function groupByCategory(groups: KbStandard[]): CategoryGroup[] {
  const byCat = new Map<string, KbStandard[]>();
  for (const g of groups) {
    const cat = categoryOf(g);
    const list = byCat.get(cat) ?? [];
    list.push(g);
    byCat.set(cat, list);
  }
  const out: CategoryGroup[] = [];
  for (const cat of CATEGORY_ORDER) {
    const standards = byCat.get(cat);
    if (standards && standards.length > 0) {
      out.push({ category: cat, label: CATEGORY_LABEL[cat], standards });
      byCat.delete(cat);
    }
  }
  for (const [cat, standards] of byCat) {
    out.push({ category: cat, label: cat, standards });
  }
  return out;
}

/** Case-insensitive substring match on disclosure id, title, or standard name. */
export function matchesQuery(
  d: KbDisclosure,
  standardName: string,
  query: string,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    d.id.toLowerCase().includes(q) ||
    d.title.toLowerCase().includes(q) ||
    standardName.toLowerCase().includes(q)
  );
}

/**
 * Whether a disclosure should be shown under the active filters. Search and
 * the edition filter compose with AND. The edition filter hides non-current
 * editions, EXCEPT a non-current disclosure that is currently selected always
 * stays visible — so a selection can never be silently hidden.
 */
export function disclosureVisible(
  d: KbDisclosure,
  standardName: string,
  opts: { query: string; currentOnly: boolean; selected: Set<string> },
): boolean {
  if (!matchesQuery(d, standardName, opts.query)) return false;
  if (opts.currentOnly && d.status !== "current" && !opts.selected.has(d.id)) {
    return false;
  }
  return true;
}
