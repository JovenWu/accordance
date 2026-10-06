"""Summarise an effort_ab.py run: agreement, tokens, latency, cost.

Agreement is the headline because it needs no ground truth. If two settings
return the same verdict on nearly every disclosure, the expensive one is
buying nothing and the cheap one wins outright. Only the disagreements are
worth a human's time to adjudicate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from accordance.pricing import DEFAULT_PRICES, cost_usd

MODEL = "gpt-5.6-luna"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="../eval/reports/effort_ab.json")
    ap.add_argument("--per-pdf-disclosures", type=int, default=217)
    args = ap.parse_args()

    data = json.loads(pathlib.Path(args.file).read_text(encoding="utf-8"))
    efforts: list[str] = []
    for v in data.values():
        for e in v:
            if e not in efforts:
                efforts.append(e)

    bad = ("EXC", "PARSE_FAIL")
    ok = {
        e: {d: r[e] for d, r in data.items() if e in r and r[e]["status"] not in bad}
        for e in efforts
    }
    print(f"disclosures: {len(data)}   settings: {efforts}\n")

    print(f"{'effort':<8} {'n':>3} {'out tok':>9} {'med out':>8} {'latency':>9} {'$/PDF@217':>10}")
    print("-" * 54)
    for e in efforts:
        rs = list(ok[e].values())
        if not rs:
            print(f"{e:<8}   0   (all failed)")
            continue
        avg_in = st.mean(r["in_tok"] for r in rs)
        avg_out = st.mean(r["out_tok"] for r in rs)
        avg_cached = st.mean(r.get("cached_tok", 0) for r in rs)
        per_pdf = cost_usd(
            MODEL,
            int(avg_in * args.per_pdf_disclosures),
            int(avg_out * args.per_pdf_disclosures),
            DEFAULT_PRICES,
            cached_tokens=int(avg_cached * args.per_pdf_disclosures),
        )
        print(
            f"{e:<8} {len(rs):>3} {avg_out:>9,.0f} "
            f"{st.median(r['out_tok'] for r in rs):>8,.0f} "
            f"{st.mean(r['latency_s'] for r in rs):>8.1f}s {per_pdf:>10.3f}"
        )

    failures = [(d, e) for d, v in data.items() for e in v if v[e]["status"] in bad]
    if failures:
        print(f"\nfailed calls ({len(failures)}): {failures[:8]}")

    print("\n=== verdict agreement ===")
    for i, a in enumerate(efforts):
        for b in efforts[i + 1 :]:
            both = sorted(set(ok[a]) & set(ok[b]))
            if not both:
                continue
            same = [d for d in both if ok[a][d]["status"] == ok[b][d]["status"]]
            diff = [d for d in both if d not in same]
            print(f"{a} vs {b}: {len(same)}/{len(both)} = {len(same)/len(both)*100:.0f}% agree")
            for d in diff:
                print(f"    {d:<7} {a}={ok[a][d]['status']:<8} {b}={ok[b][d]['status']}")

            e_tot = e_same = 0
            for d in both:
                ea, eb = ok[a][d].get("elements", {}), ok[b][d].get("elements", {})
                for k in set(ea) & set(eb):
                    e_tot += 1
                    e_same += ea[k] == eb[k]
            if e_tot:
                print(f"  element-level: {e_same}/{e_tot} = {e_same/e_tot*100:.0f}% agree")

    print("\n=== status distribution ===")
    for e in efforts:
        c: dict[str, int] = {}
        for r in ok[e].values():
            c[r["status"]] = c.get(r["status"], 0) + 1
        print(f"  {e:<8} {dict(sorted(c.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
