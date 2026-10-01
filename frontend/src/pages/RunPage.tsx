import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { getReport, getRun, isNotFound } from "@/api";
import { useSSE } from "@/api/useSSE";
import { EvidenceViewerProvider } from "@/components/EvidenceViewerProvider";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RunHeader } from "@/components/run/RunHeader";
import { LiveRunView } from "@/components/run/LiveRunView";
import { FailedRunView } from "@/components/run/FailedRunView";
import { FindingsView } from "@/components/run/FindingsView";
import { CorrectionModal } from "@/components/run/CorrectionModal";
import { TraceDrawer } from "@/components/run/TraceDrawer";
import type { FindingView, RunDetail, RunStatus } from "@/types";

const LIVE_STATUSES: RunStatus[] = ["queued", "extracting", "indexing", "judging"];

export function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [reportName, setReportName] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tracesOpen, setTracesOpen] = useState(false);
  const [correcting, setCorrecting] = useState<FindingView | null>(null);
  const [traceFor, setTraceFor] = useState<FindingView | null>(null);
  const seq = useRef(0);
  const refetchTimer = useRef<number | null>(null);

  const load = useCallback(async (runId: string) => {
    const mySeq = ++seq.current;
    try {
      const r = await getRun(runId);
      if (seq.current !== mySeq) return;
      setRun(r);
      setError(null);
      setMissing(false);
    } catch (e) {
      if (seq.current !== mySeq) return;
      if (isNotFound(e)) setMissing(true);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (id) void load(id);
  }, [id, load]);

  // Report name for the breadcrumb — one extra call once report_id is known.
  useEffect(() => {
    if (!run?.report_id) return;
    let stale = false;
    getReport(run.report_id)
      .then((r) => !stale && setReportName(r.name))
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [run?.report_id]);

  const live = run ? LIVE_STATUSES.includes(run.summary.status) : false;

  // Poll as the authoritative stage source — SSE only carries finding/terminal
  // events, so the stepper and progress bar come from the polled run summary.
  useEffect(() => {
    if (!id || !live) return;
    const t = setInterval(() => void load(id), 3000);
    return () => clearInterval(t);
  }, [id, live, load]);

  // SSE: on each judged finding, schedule a debounced refetch so the feed and
  // counts grow as the judge works; terminal events force an immediate fetch.
  const onEvent = useCallback(
    (msg: { type?: string }) => {
      if (!id) return;
      if (msg.type === "finding") {
        if (refetchTimer.current !== null) return;
        refetchTimer.current = window.setTimeout(() => {
          refetchTimer.current = null;
          void load(id);
        }, 400);
      } else if (
        msg.type === "completed" ||
        msg.type === "cancelled" ||
        msg.type === "failed"
      ) {
        void load(id);
      }
    },
    [id, load],
  );
  useSSE(live ? (id ?? null) : null, onEvent);

  useEffect(
    () => () => {
      if (refetchTimer.current !== null) clearTimeout(refetchTimer.current);
    },
    [],
  );

  const reload = useCallback(() => {
    if (id) void load(id);
  }, [id, load]);

  const crumbs = useMemo(() => {
    if (!run) return null;
    return {
      reportId: run.report_id,
      reportName: reportName ?? run.summary.pdf_filename,
      version: run.version_number,
      kind: run.kind,
    };
  }, [run, reportName]);

  if (missing) {
    return (
      <NotFoundPage
        title="Run not found"
        message="That analysis run doesn't exist. It may have been deleted along with its report."
      />
    );
  }
  if (error) {
    return (
      <div className="grid flex-1 place-items-center p-4 sm:p-6 lg:p-10">
        <p className="text-sm text-danger">{error}</p>
      </div>
    );
  }
  if (!run || !crumbs) {
    return (
      <div className="grid flex-1 place-items-center p-4 text-muted-ink sm:p-6 lg:p-10">
        Loading…
      </div>
    );
  }

  return (
    <EvidenceViewerProvider
      runId={run.summary.id}
      pdfFilename={run.summary.pdf_filename}
      versionNumber={run.version_number}
      onCorrect={setCorrecting}
      onTrace={setTraceFor}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
        <Link
          to={`/reports/${crumbs.reportId}`}
          className="flex w-fit items-center gap-1.5 text-[13px] text-muted-ink hover:text-ink"
        >
          <ArrowLeft className="size-4" aria-hidden />
          <span className="font-medium">{crumbs.reportName}</span>
          <span>
            / Run v{crumbs.version} · {crumbs.kind}
          </span>
        </Link>

        <RunHeader
          run={run}
          onChanged={reload}
          onOpenTraces={() => setTracesOpen(true)}
        />

        <RunBody
          run={run}
          onChanged={reload}
          onCorrect={setCorrecting}
          onTrace={setTraceFor}
        />
      </div>

      {tracesOpen && (
        <TraceDrawer run={run} onClose={() => setTracesOpen(false)} />
      )}
      {traceFor && (
        <TraceDrawer
          run={run}
          disclosureId={traceFor.disclosure_id}
          onClose={() => setTraceFor(null)}
        />
      )}
      {correcting && (
        <CorrectionModal
          run={run}
          finding={correcting}
          existing={correctionMap(run)[correcting.disclosure_id]}
          onClose={() => setCorrecting(null)}
          onSaved={() => {
            setCorrecting(null);
            reload();
          }}
        />
      )}
    </EvidenceViewerProvider>
  );
}

function correctionMap(run: RunDetail) {
  const m: Record<string, import("@/types").CorrectionView> = {};
  for (const c of run.corrections) m[c.disclosure_id] = c;
  return m;
}

function RunBody({
  run,
  onChanged,
  onCorrect,
  onTrace,
}: {
  run: RunDetail;
  onChanged: () => void;
  onCorrect: (f: FindingView) => void;
  onTrace: (f: FindingView) => void;
}) {
  const status = run.summary.status;
  if (LIVE_STATUSES.includes(status)) {
    return <LiveRunView run={run} onChanged={onChanged} />;
  }
  if (status === "failed") {
    return <FailedRunView run={run} onChanged={onChanged} />;
  }
  return (
    <FindingsView
      run={run}
      onChanged={onChanged}
      onCorrect={onCorrect}
      onTrace={onTrace}
    />
  );
}
