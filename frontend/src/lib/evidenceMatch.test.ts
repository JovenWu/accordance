import { describe, expect, it } from "vitest";

import {
  computeHighlightRanges,
  escapeHtml,
  markItem,
  normalize,
  type PdfTextItem,
} from "./evidenceMatch";

/** Helper: the concatenated text a set of ranges would wrap, per item. */
function markedText(items: PdfTextItem[], excerpt: string | null): string[] {
  const ranges = computeHighlightRanges(items, excerpt);
  const out: string[] = [];
  for (const [idx, [a, b]] of [...ranges.entries()].sort((x, y) => x[0] - y[0])) {
    out.push(items[idx].str.slice(a, b));
  }
  return out;
}

describe("normalize", () => {
  it("lowercases, drops quotes, and collapses whitespace", () => {
    expect(normalize('  "Legal   Name"  ')).toBe("legal name");
  });

  it("folds the fi ligature so excerpt and PDF text agree", () => {
    expect(normalize("ﬁnancial")).toBe("financial");
  });

  it("treats non-breaking and thin spaces as a normal space", () => {
    expect(normalize("Scope 1 emissions")).toBe("scope 1 emissions");
  });

  it("unifies unicode dashes to a hyphen", () => {
    expect(normalize("2024–2025")).toBe("2024-2025");
  });

  it("drops thousands separators between digits", () => {
    expect(normalize("1,234,567")).toBe("1234567");
  });
});

describe("computeHighlightRanges", () => {
  it("returns an empty map for a null excerpt", () => {
    expect(computeHighlightRanges([{ str: "anything" }], null).size).toBe(0);
  });

  it("highlights a phrase that spans multiple pdf.js items", () => {
    const items: PdfTextItem[] = [{ str: "Total Scope 1" }, { str: "emissions" }];
    expect(markedText(items, "Total Scope 1 emissions")).toEqual([
      "Total Scope 1",
      "emissions",
    ]);
  });

  it("highlights only the cited phrase inside a longer line (the key fix)", () => {
    // Old code failed here: the span is LONGER than the excerpt, so
    // `excerpt.includes(span)` was false and nothing lit up.
    const items: PdfTextItem[] = [
      { str: "Our total Scope 1 emissions were 1,234 tCO2e in 2023" },
    ];
    expect(markedText(items, "total Scope 1 emissions were 1,234 tCO2e")).toEqual([
      "total Scope 1 emissions were 1,234 tCO2e",
    ]);
  });

  it("matches a short phrase contained in one item, ignoring case", () => {
    const items: PdfTextItem[] = [
      { str: "The company's legal name is Acme Corporation Ltd." },
    ];
    expect(markedText(items, 'legal name is "Acme Corporation"')).toEqual([
      "legal name is Acme Corporation",
    ]);
  });

  it("falls back to the longest verbatim run when the excerpt is paraphrased", () => {
    // The LLM dropped "for the" and inserted "metric" — no exact substring,
    // but the contiguous run still anchors the highlight to the right place.
    const items: PdfTextItem[] = [
      { str: "Scope 1 emissions for the fiscal year 2024 totaled 12,450 tonnes" },
    ];
    const marked = markedText(
      items,
      "emissions fiscal year 2024 totaled 12,450 metric tonnes",
    );
    expect(marked.length).toBe(1);
    expect(marked[0]).toContain("fiscal year 2024 totaled 12,450");
  });

  it("returns an empty map when nothing matches", () => {
    const items: PdfTextItem[] = [{ str: "emissions report 2024" }];
    expect(computeHighlightRanges(items, "completely unrelated content").size).toBe(
      0,
    );
  });

  it("ignores a stray short common word (no spurious box)", () => {
    const items: PdfTextItem[] = [{ str: "and then the meeting adjourned" }];
    // "the" alone should not anchor a highlight across an unrelated excerpt.
    expect(
      computeHighlightRanges(items, "the board approved a new climate policy").size,
    ).toBe(0);
  });

  it("does not highlight an excerpt reworded in its middle (deliberate recall trade-off)", () => {
    // Interior paraphrase: the longest contiguous run (" scope 1 emissions by
    // 12") is <50% of the excerpt, so it fails safe to no box rather than
    // mis-anchoring. Pinned so the precision-over-recall choice is intentional.
    const items: PdfTextItem[] = [
      { str: "We cut scope 1 emissions by 12 percent versus the prior year" },
    ];
    const excerpt =
      "We reduced scope 1 emissions by 12% versus the prior reporting year";
    expect(computeHighlightRanges(items, excerpt).size).toBe(0);
  });

  it("rejects a longer common run that is only a small fraction of the excerpt", () => {
    // "our sustainability metrics" (>12 chars) clears the absolute floor but is
    // a small slice of this long, unrelated emissions claim — without a
    // coverage gate it would mis-anchor a box on the wrong phrase.
    const items: PdfTextItem[] = [
      { str: "We publish our sustainability metrics each year." },
    ];
    const excerpt =
      "Scope 1 greenhouse gas emissions were 12,450 tonnes per our sustainability metrics dashboard";
    expect(computeHighlightRanges(items, excerpt).size).toBe(0);
  });
});

describe("markItem", () => {
  it("wraps the given range in <mark> and escapes the rest", () => {
    expect(markItem("hello world", [0, 5])).toBe("<mark>hello</mark> world");
  });

  it("escapes html when there is no range", () => {
    expect(markItem("a < b & c", undefined)).toBe("a &lt; b &amp; c");
  });

  it("escapes inside and outside the mark", () => {
    expect(markItem("x<y>z", [1, 4])).toBe("x<mark>&lt;y&gt;</mark>z");
  });
});

describe("escapeHtml", () => {
  it("escapes angle brackets and ampersands", () => {
    expect(escapeHtml("a < b & c > d")).toBe("a &lt; b &amp; c &gt; d");
  });
});
