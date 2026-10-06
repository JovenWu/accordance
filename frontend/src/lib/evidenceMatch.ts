export interface PdfTextItem {
  str: string;
  hasEOL?: boolean;
}

const DROP = new Set([
  '"', "'", "`", "´",
  "‘", "’", "‚", "‛",
  "“", "”", "„", "‟",
  "′", "″",
  "­", "​", "‌", "‍", "⁠",
]);

const DASH = new Set([
  "‐", "‑", "‒", "–", "—", "―", "−", "⁃",
]);

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

function mapChar(ch: string): string {
  if (DROP.has(ch)) return "";
  if (/\s/.test(ch)) return " ";
  const lig = LIGATURES[ch];
  if (lig !== undefined) return lig;
  if (DASH.has(ch)) return "-";
  return ch.toLowerCase();
}

function normalizeWithMap(raw: string): { norm: string; map: number[] } {
  const chars: string[] = [];
  const map: number[] = [];
  let prevSpace = true;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (ch === "," && isDigit(raw[i - 1]) && isDigit(raw[i + 1])) continue;
    const mapped = mapChar(ch);
    if (mapped === "") continue;
    if (mapped === " ") {
      if (prevSpace) continue;
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
  while (chars.length > 0 && chars[chars.length - 1] === " ") {
    chars.pop();
    map.pop();
  }
  return { norm: chars.join(""), map };
}

export function normalize(s: string): string {
  return normalizeWithMap(s).norm;
}

const MIN_FUZZY_CHARS = 12;

const MIN_FUZZY_COVERAGE = 0.5;

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

export function computeHighlightRanges(
  items: PdfTextItem[],
  excerpt: string | null,
): Map<number, [number, number]> {
  const result = new Map<number, [number, number]>();
  if (!excerpt || !excerpt.trim() || items.length === 0) return result;

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

  const { norm, map } = normalizeWithMap(raw);
  const needle = normalize(excerpt);
  if (needle.length === 0 || norm.length === 0) return result;

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

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

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
