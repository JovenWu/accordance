import { useEffect, useState } from "react";
import { FileText, Search } from "lucide-react";

import { getTraces } from "@/api";
import { Drawer } from "@/components/ui/drawer";
import { useKbTitles } from "@/lib/useKbTitles";
import type { DisclosureTrace, RunDetail, TraceAttempt } from "@/types";

export function TraceDrawer({
  run,
  disclosureId,
  onClose,
}: {
  run: RunDetail;
  /** When set, only this disclosure's trace is shown. */
  disclosureId?: string;
  onClose: () => void;
}) {
  const titles = useKbTitles();
  const [traces, setTraces] = useState<DisclosureTrace[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    getTraces(run.summary.id)
      .then((r) => !stale && setTraces(r.traces))
      .catch((e) => !stale && setError(String(e)));
    return () => {
      stale = true;
    };
  }, [run.summary.id]);

  const shown = disclosureId
    ? traces?.filter((t) => t.disclosure_id === disclosureId)
    : traces;

  return (
    <Drawer
      open
      title="Judge trace"
      subtitle={
        disclosureId
          ? `${disclosureId}${titles.get(disclosureId) ? ` — ${titles.get(disclosureId)}` : ""}`
          : `Run v${run.version_number} · ${traces?.length ?? "…"} disclosures`
      }
      onClose={onClose}
    >
      <div className="flex flex-col gap-3.5 p-5">
        {error && <p className="text-sm text-danger">{error}</p>}
        {!error && traces === null && (
          <p className="text-sm text-muted-ink">Loading traces…</p>
        )}
        {shown?.map((t) => <TraceSection key={t.disclosure_id} trace={t} />)}
        {shown?.length === 0 && (
          <p className="text-sm text-muted-ink">
            No trace recorded for this disclosure.
          </p>
        )}
      </div>
    </Drawer>
  );
}

function TraceSection({ trace }: { trace: DisclosureTrace }) {
  const latest = trace.attempts[trace.attempts.length - 1];
  return (
    <section className="flex flex-col gap-3.5 border-b border-line pb-5 last:border-0">
      <span className="text-[13px] font-semibold text-ink">
        {trace.disclosure_id}
        <span className="ml-2 font-normal text-muted-ink">
          attempt {latest?.attempt ?? "?"} of {trace.attempts.length}
        </span>
      </span>
      {latest && <AttemptMeta attempt={latest} />}
      {latest && <Retrieval attempt={latest} />}
      <AttemptList attempts={trace.attempts} />
      {latest?.prompt_hash && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold text-muted-ink">
            Prompt
          </span>
          <div className="flex flex-col gap-1 rounded-md bg-soft-2 p-2.5">
            <span className="text-[11px] text-muted-ink">
              hash sha256:{latest.prompt_hash.slice(0, 4)}…
              {latest.prompt_hash.slice(-4)}
            </span>
            <span className="text-[11px] text-muted-ink">
              system + KB requirement + {latest.chunk_ids.length} evidence
              chunks
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

function MetaRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between">
      <span className="text-xs text-muted-ink">{k}</span>
      <span className="text-right text-xs font-medium text-ink">{v}</span>
    </div>
  );
}

function AttemptMeta({ attempt: a }: { attempt: TraceAttempt }) {
  return (
    <div className="flex flex-col gap-1.5 bg-soft-2 p-3">
      <MetaRow k="Model" v={a.model} />
      <MetaRow
        k="Latency"
        v={a.latency_ms != null ? `${(a.latency_ms / 1000).toFixed(1)} s` : "—"}
      />
      <MetaRow
        k="Parse"
        v={a.error ? `${a.parse_path} · ${a.error}` : `${a.parse_path} · ok`}
      />
      <MetaRow
        k="Evidence"
        v={
          a.evidence_verified === true
            ? "verified — excerpt found in text"
            : a.evidence_verified === false
              ? "not verified"
              : "—"
        }
      />
    </div>
  );
}

function Retrieval({ attempt: a }: { attempt: TraceAttempt }) {
  const pages = a.pages;
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[11px] font-semibold text-muted-ink">
        Retrieval
      </span>
      {a.queries.map((q, i) => (
        <div
          key={i}
          className="flex items-center gap-2 rounded-md bg-soft-2 px-2.5 py-1.5"
        >
          <Search className="size-3.5 shrink-0 text-muted-ink" aria-hidden />
          <span className="flex-1 text-xs text-ink">“{q}”</span>
        </div>
      ))}
      {a.chunk_ids.map((cid, i) => {
        const d = a.distances[i];
        const width =
          d == null ? 0 : Math.max(2, Math.min(100, (1 - d) * 100));
        return (
          <div key={cid} className="flex items-center gap-2 px-2.5 py-1">
            <FileText
              className="size-3.5 shrink-0 text-muted-ink"
              aria-hidden
            />
            <span className="text-xs font-medium text-ink">chunk {cid}</span>
            {pages[i] != null && (
              <span className="text-xs text-muted-ink">p.{pages[i]}</span>
            )}
            <span className="h-1 flex-1 overflow-hidden rounded-[2px] bg-soft-2">
              <span
                className="block h-full bg-accent"
                style={{ width: `${width}%` }}
              />
            </span>
            {d != null && (
              <span className="text-[11px] tabular-nums text-muted-ink">
                {d.toFixed(2)}
              </span>
            )}
          </div>
        );
      })}
      {a.rejudged && (
        <span className="text-[11px] text-muted-ink">
          + re-judge pass — retried after a parse/validation failure
        </span>
      )}
    </div>
  );
}

function AttemptList({ attempts }: { attempts: TraceAttempt[] }) {
  if (attempts.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold text-muted-ink">
        Attempts
      </span>
      {attempts.map((a) => (
        <div
          key={a.attempt}
          className="flex items-start justify-between rounded-md bg-soft-2 px-2.5 py-[7px]"
        >
          <span className="text-xs font-medium text-ink">
            {a.attempt} — {a.rejudged ? "re-judge" : "initial pass"}
          </span>
          <span className="text-[11px] text-muted-ink">
            {a.parse_path}
            {a.latency_ms != null &&
              ` · ${(a.latency_ms / 1000).toFixed(1)} s`}
          </span>
        </div>
      ))}
    </div>
  );
}
