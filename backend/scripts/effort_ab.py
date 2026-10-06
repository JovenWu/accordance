"""A/B a judge model's `reasoning_effort` against an already-indexed run.

Reasoning tokens bill as OUTPUT, so effort is a direct cost/latency lever.
This measures what it costs AND whether it changes the answer.

Deliberately compares the arms to EACH OTHER, not to ground-truth labels:
the ptvi-2024 gold set is 69% "covered", so a judge that always answers
"covered" already scores 69% and raw accuracy cannot separate these settings.
Verdict AGREEMENT needs no labels at all. High agreement => take the cheap
setting outright; the disagreements are the only disclosures worth
hand-adjudicating.

Retrieval is REPLAYED from judge_traces.chunk_ids rather than re-run: the
embedding account has no credits, and replay is strictly better for this
experiment anyway — every arm gets a byte-identical prompt, so reasoning
effort is the only variable. chunk_ids are stored in prompt order (they are
the `merged` list judge_disclosure rendered), so they must NOT be re-sorted.

Usage (from backend/, with the dev stack up):
    python scripts/effort_ab.py --run-id <run> --efforts none,medium
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))


def _load_env(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env(pathlib.Path(__file__).resolve().parents[2] / ".env")
os.environ["DATABASE_URL"] = os.environ.get(
    "AB_DATABASE_URL", "postgresql://gri:gri@127.0.0.1:5433/gri"
)

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from accordance.config import get_settings  # noqa: E402
from accordance.judge.core import _extract_json  # noqa: E402
from accordance.judge.output_schema import JudgeOutput  # noqa: E402
from accordance.judge.prompts import (  # noqa: E402
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    render_chunks,
    render_elements_list,
    render_hints,
)
from accordance.kb.loader import load_kb  # noqa: E402

KB_DIR = pathlib.Path(__file__).resolve().parents[2] / "kb" / "gri"


def build_prompts(conn, run_id: str, kb: dict) -> dict[str, str]:
    """Rebuild each disclosure's exact judge prompt from its stored trace."""
    rows = conn.execute(
        "SELECT disclosure_id, chunk_ids_json FROM judge_traces "
        "WHERE run_id=%s AND rejudged = false ORDER BY id",
        (run_id,),
    ).fetchall()

    prompts: dict[str, str] = {}
    for r in rows:
        did = r["disclosure_id"]
        if did in prompts or did not in kb:
            continue
        ids = json.loads(r["chunk_ids_json"])
        if not ids:
            continue
        got = {
            c["id"]: c
            for c in conn.execute(
                "SELECT id, page, text FROM chunks WHERE id = ANY(%s)", (ids,)
            ).fetchall()
        }
        merged = [
            {"page": got[i]["page"], "text": got[i]["text"]} for i in ids if i in got
        ]
        if not merged:
            continue
        d = kb[did]
        prompts[did] = USER_TEMPLATE.format(
            disclosure_id=d.id,
            disclosure_title=d.title,
            standard=d.standard,
            requirement_text=d.requirement_text,
            elements_list=render_elements_list(d.required_elements),
            evidence_hints=render_hints(d.good_evidence_hints),
            retrieved_chunks=render_chunks(merged),
        )
    return prompts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--efforts", default="none,medium")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--sleep", type=float, default=2.0, help="pause between calls")
    ap.add_argument("--out", default="../eval/reports/effort_ab.json")
    args = ap.parse_args()

    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
    settings = get_settings()
    base_url = settings.llm_base_url.replace("host.docker.internal", "localhost")
    kb = load_kb(KB_DIR)

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        prompts = build_prompts(conn, args.run_id, kb)
    ids = sorted(prompts)[: args.limit]
    print(f"model={settings.llm_model}  efforts={efforts}", flush=True)
    print(f"replayed prompts: {len(ids)} disclosures from run {args.run_id}", flush=True)

    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=settings.llm_api_key, max_retries=5, timeout=300.0)
    model = settings.llm_model.rsplit(":", 1)[-1]

    results: dict[str, dict] = {}
    for effort in efforts:
        print(f"\n=== effort={effort} ===", flush=True)
        for i, did in enumerate(ids, 1):
            t0 = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    reasoning_effort=effort,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompts[did]},
                    ],
                )
                content = resp.choices[0].message.content or ""
                u = resp.usage
                cached = getattr(
                    getattr(u, "prompt_tokens_details", None), "cached_tokens", 0
                ) or 0
                try:
                    out = JudgeOutput.model_validate_json(_extract_json(content))
                    status, elements = out.status.value, {
                        e.id: e.status.value for e in out.elements
                    }
                    applicable = bool(out.applicable)
                except Exception:
                    status, elements, applicable = "PARSE_FAIL", {}, None
                rec = {
                    "status": status,
                    "applicable": applicable,
                    "elements": elements,
                    "in_tok": u.prompt_tokens,
                    "out_tok": u.completion_tokens,
                    "cached_tok": cached,
                    "latency_s": round(time.time() - t0, 1),
                }
            except Exception as e:
                rec = {"status": "EXC", "error": f"{type(e).__name__}: {str(e)[:160]}"}
            results.setdefault(did, {})[effort] = rec
            print(
                f"  [{i:>2}/{len(ids)}] {did:<7} {rec['status']:<11} "
                f"out={rec.get('out_tok', 0):>5} {rec.get('latency_s', 0):>6}s",
                flush=True,
            )
            time.sleep(args.sleep)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
