/**
 * Evidence → PDF highlight matching.
 *
 * The judge cites an `evidence_excerpt` (a quote) and a page. To draw the box
 * we must find that quote inside the page's pdf.js text layer. The reliable way
 * is NOT to ask "is this span inside the excerpt?" (which misses whenever a span
 * is a whole line, the phrase straddles several spans, or the excerpt is lightly
 * reworded). Instead we:
 *
 *   1. concatenate the page's text items into one string, remembering each
 *      item's character range;
 *   2. normalize the page string and the excerpt the same way, keeping a map
 *      from each normalized char back to its raw offset;
 *   3. locate the excerpt in the normalized page string (exact substring, or
 *      the longest contiguous run as a fuzzy fallback for paraphrases);
 *   4. mark every text item whose range overlaps the matched range.
 *
 * This is the same find-then-map-back approach pdf.js's own search uses.
 */

/** A pdf.js text-layer item, as delivered by react-pdf's onGetTextSuccess. */
export interface PdfTextItem {
  str: string;
  hasEOL?: boolean;
}

// Characters dropped entirely during normalization: quotes/apostrophes (so a
// PDF's straight quote matches an excerpt's curly one), soft hyphen, and
// zero-width marks.
const DROP = new Set([
  '"', "'", "`", "´",
  "‘", "’", "‚", "‛",
  "“", "”", "„", "‟",
  "′", "″",
  "­", "​", "‌", "‍", "⁠",
]);

// Unicode dashes/minus folded to an ASCII hyphen.
const DASH = new Set([
  "‐", "‑", "‒", "–", "—", "―", "−", "⁃",
]);

// Ligatures expanded so "ﬁnancial" matches "financial".
const LIGATURES: Record<string, string> = {
  "ﬀ": "ff",
  "ﬁ": "fi",
  "ﬂ": "fl",
  "ﬃ": "ffi",
  "ﬄ": "ffl",
  "ﬅ": "st",
  "ﬆ": "st",
};

function isDigit(ch: string | undefined): boolean {
  return ch !== undefined && ch >= "0" && ch <= "9";
}

/** Normalize a single character to its canonical form ("" = drop, " " = space). */
function mapChar(ch: string): string {
  if (DROP.has(ch)) return "";
  if (/\s/.test(ch)) return " ";
  const lig = LIGATURES[ch];
  if (lig !== undefined) return lig;
  if (DASH.has(ch)) return "-";
  return ch.toLowerCase();
}

/**
 * Normalize `raw`, returning the normalized string plus a parallel array
 * mapping each normalized char index back to its source index in `raw`.
 */
function normalizeWithMap(raw: string): { norm: string; map: number[] } {
  const chars: string[] = [];
  const map: number[] = [];
  let prevSpace = true; // start true to trim leading whitespace
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    // Thousands separators inside numbers ("1,234" → "1234").
    if (ch === "," && isDigit(raw[i - 1]) && isDigit(raw[i + 1])) continue;
    const mapped = mapChar(ch);
    if (mapped === "") continue;
    if (mapped === " ") {
      if (prevSpace) continue; // collapse runs of whitespace
      chars.push(" ");
      map.push(i);
      prevSpace = true;
      continue;
    }
    for (const c of mapped) {
      chars.push(c);
      map.push(i);
    }
    prevSpace = false;
  }
  // Trim trailing whitespace.
  while (chars.length > 0 && chars[chars.length - 1] === " ") {
    chars.pop();
    map.pop();
  }
  return { norm: chars.join(""), map };
}

/** Normalize text for fuzzy, layout-insensitive comparison. */
export function normalize(s: string): string {
  return normalizeWithMap(s).norm;
}

// A fuzzy fallback only fires when an exact match fails; require a run of at
// least this many normalized chars so a stray common word ("the ") can't
// anchor a highlight onto unrelated text.
const MIN_FUZZY_CHARS = 12;

// …and the run must cover at least this fraction of the excerpt, so a longer
// run that is still only a small slice of a long quote ("our sustainability
// metrics" inside a paragraph about emissions) can't mis-anchor a box on the
// wrong phrase. Exact-substring matches bypass this — short verbatim cells
// still highlight. Deliberate precision-over-recall trade-off: an excerpt
// reworded in its MIDDLE (so its longest contiguous run is <50% of it) no
// longer highlights — it fails safe to no box rather than a wrong box. This is
// acceptable because the judge prompt requires verbatim excerpts and the
// backend snaps them to real page text, so interior paraphrases are rare.
const MIN_FUZZY_COVERAGE = 0.5;

/**
 * Longest substring of `needle` that occurs contiguously in `hay`.
 * Returns its position in `hay`, or null if there is no common character.
 */
function longestCommonRun(
  hay: string,
  needle: string,
): { start: number; len: number } | null {
  const n = hay.length;
  const m = needle.length;
  if (n === 0 || m === 0) return null;
  let prev = new Array<number>(m + 1).fill(0);
  let best = 0;
  let bestEnd = 0;
  for (let i = 1; i <= n; i++) {
    const curr = new Array<number>(m + 1).fill(0);
    const hc = hay.charCodeAt(i - 1);
    for (let j = 1; j <= m; j++) {
      if (hc === needle.charCodeAt(j - 1)) {
        curr[j] = prev[j - 1] + 1;
        if (curr[j] > best) {
          best = curr[j];
          bestEnd = i;
        }
      }
    }
    prev = curr;
  }
  if (best === 0) return null;
  return { start: bestEnd - best, len: best };
}

/**
 * Given the page's text items and the cited excerpt, return which items to
 * highlight and the local [start, end) char range within each item's `str`.
 * Empty map = no confident match (don't draw a box).
 */
export function computeHighlightRanges(
  items: PdfTextItem[],
  excerpt: string | null,
): Map<number, [number, number]> {
  const result = new Map<number, [number, number]>();
  if (!excerpt || !excerpt.trim() || items.length === 0) return result;

  // 1. Build the raw page string, inserting a virtual separator between items
  //    so adjacent runs ("Total" + "emissions") don't fuse into one word.
  let raw = "";
  const spans: { idx: number; start: number; end: number }[] = [];
  for (let k = 0; k < items.length; k++) {
    const s = items[k]?.str ?? "";
    if (raw.length > 0 && !/\s$/.test(raw) && !/^\s/.test(s)) raw += " ";
    const start = raw.length;
    raw += s;
    spans.push({ idx: k, start, end: raw.length });
    if (items[k]?.hasEOL && !/\s$/.test(raw)) raw += " ";
  }

  // 2. Normalize both sides identically.
  const { norm, map } = normalizeWithMap(raw);
  const needle = normalize(excerpt);
  if (needle.length === 0 || norm.length === 0) return result;

  // 3. Locate the excerpt: exact substring, else the longest contiguous run.
  let nStart = norm.indexOf(needle);
  let nEnd: number;
  if (nStart >= 0) {
    nEnd = nStart + needle.length;
  } else {
    const run = longestCommonRun(norm, needle);
    if (
      !run ||
      run.len < MIN_FUZZY_CHARS ||
      run.len < needle.length * MIN_FUZZY_COVERAGE
    )
      return result;
    nStart = run.start;
    nEnd = run.start + run.len;
  }

  // 4. Map the normalized range back to raw offsets, then to per-item ranges.
  if (nStart >= map.length) return result;
  const rawStart = map[nStart];
  const rawEnd = map[Math.min(nEnd, map.length) - 1] + 1;
  for (const sp of spans) {
    const os = Math.max(sp.start, rawStart);
    const oe = Math.min(sp.end, rawEnd);
    if (os < oe) result.set(sp.idx, [os - sp.start, oe - sp.start]);
  }
  return result;
}

/** Escape a string for safe insertion as innerHTML by react-pdf. */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * Render one text item to HTML, wrapping the given [start, end) range in
 * <mark>. With no range the item is returned escaped and unmarked.
 */
export function markItem(
  str: string,
  range: [number, number] | undefined,
): string {
  if (!range) return escapeHtml(str);
  const start = Math.max(0, Math.min(range[0], str.length));
  const end = Math.max(start, Math.min(range[1], str.length));
  return (
    escapeHtml(str.slice(0, start)) +
    "<mark>" +
    escapeHtml(str.slice(start, end)) +
    "</mark>" +
    escapeHtml(str.slice(end))
  );
}
