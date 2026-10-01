import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  Eye,
  FileDown,
  FilePlus,
  FileUp,
  GitCompare,
  GitFork,
  RotateCcw,
  Trash2,
} from "lucide-react";

import {
  deleteReport,
  deleteRun,
  downloadFile,
  exportReportCoverageUrl,
  forkRun,
  getReport,
  isNotFound,
  renameReport,
  retryRun,
  uploadNewVersion,
} from "@/api";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip, RunStatusChip } from "@/components/ui/chip";
import { Field, Input } from "@/components/ui/input";
import { KebabMenu } from "@/components/ui/menu";
import { Modal, ModalIconTile } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat-card";
import { TableCard, Table, THead, Th, Td } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/datetime";
import type { ReportDetail, RunStatus, VersionSummary } from "@/types";

const TERMINAL: RunStatus[] = ["completed", "failed", "cancelled"];

function findingsTotal(v: VersionSummary): number | null {
  const c = v.counts;
  const n = (c.covered ?? 0) + (c.partial ?? 0) + (c.missing ?? 0) + (c.error ?? 0);
  return n > 0 ? n : null;
}

function coverageOf(v: VersionSummary | undefined): {
  pct: string;
  detail: string;
} | null {
  if (!v) return null;
  const c = v.counts;
  const total = (c.covered ?? 0) + (c.partial ?? 0) + (c.missing ?? 0);
  if (total === 0) return null;
  const cov = (c.covered ?? 0) + (c.partial ?? 0);
  return {
    pct: `${Math.round((cov / total) * 100)}%`,
    detail: `${cov} of ${total} covered or partial`,
  };
}

export function ReportPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const nav = useNavigate();
  const { toast } = useToast();
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletingRun, setDeletingRun] = useState<VersionSummary | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  const load = useCallback(async (id: string) => {
    const mySeq = ++seq.current;
    try {
      const r = await getReport(id);
      if (seq.current === mySeq) {
        setReport(r);
        setError(null);
        setMissing(false);
      }
    } catch (e) {
      if (seq.current !== mySeq) return;
      if (isNotFound(e)) setMissing(true);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (reportId) void load(reportId);
  }, [reportId, load]);

  // Poll while any version is non-terminal; keep picked-set entries that still
  // exist so a deleted version doesn't linger in the compare selection.
  useEffect(() => {
    if (!reportId || !report) return;
    const active = report.runs.some((v) => !TERMINAL.includes(v.status));
    const live = new Set(report.runs.map((v) => v.run_id));
    setPicked((cur) => {
      const next = new Set([...cur].filter((id) => live.has(id)));
      return next.size === cur.size ? cur : next;
    });
    if (!active) return;
    const t = setInterval(() => void load(reportId), 4000);
    return () => clearInterval(t);
  }, [reportId, report, load]);

  async function doUpload(f: File) {
    if (!reportId) return;
    if (f.type !== "application/pdf" && !f.name.endsWith(".pdf")) {
      toast({ title: "Not a PDF", message: f.name, variant: "error" });
      return;
    }
    setUploading(true);
    try {
      const r = await uploadNewVersion(reportId, f);
      toast({ title: `Version v${r.version_number} started`, message: f.name });
      nav(`/runs/${r.run_id}/live`);
    } catch (e) {
      toast({
        title: "Upload failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    } finally {
      setUploading(false);
    }
  }

  async function doDeleteReport() {
    if (!reportId || !report) return;
    try {
      await deleteReport(reportId);
      toast({ title: "Report deleted", message: `“${report.name}” removed.` });
      nav("/");
    } catch (e) {
      toast({
        title: "Delete failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  async function doDeleteRun() {
    const v = deletingRun;
    if (!v) return;
    try {
      await deleteRun(v.run_id);
      setDeletingRun(null);
      toast({ title: `Version v${v.version_number} deleted` });
      if (reportId) void load(reportId);
    } catch (e) {
      toast({
        title: "Delete failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  async function doRetry(v: VersionSummary) {
    try {
      const r = await retryRun(v.run_id);
      toast({ title: `Retry started as v${r.version_number}` });
      nav(`/runs/${r.run_id}/live`);
    } catch (e) {
      toast({
        title: "Retry failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  async function doFork(v: VersionSummary) {
    try {
      const r = await forkRun(v.run_id);
      toast({ title: `Forked as v${r.version_number}` });
      nav(`/runs/${r.run_id}/live`);
    } catch (e) {
      toast({
        title: "Fork failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  if (missing) {
    return (
      <NotFoundPage
        title="Report not found"
        message="This report doesn't exist, was deleted, or belongs to another account."
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
  if (!report) {
    return (
      <div className="grid flex-1 place-items-center p-4 text-muted-ink sm:p-6 lg:p-10">
        Loading…
      </div>
    );
  }

  const runs = [...report.runs].sort(
    (a, b) => b.version_number - a.version_number,
  );
  const latest = runs[0];
  const coverage = coverageOf(latest);
  const kinds = [...new Set(runs.map((r) => r.kind))].join(" · ");
  const nextVersion = (latest?.version_number ?? 0) + 1;
  const pickedRuns = runs.filter((v) => picked.has(v.run_id));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <Link
        to="/"
        className="flex w-fit items-center gap-1.5 text-[13px] text-muted-ink hover:text-ink"
      >
        <ArrowLeft className="size-4" aria-hidden />
        <span className="font-medium">Analyses</span>
        <span>/ {report.name}</span>
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="truncate text-xl font-semibold text-ink">
            {report.name}
          </h1>
          <p className="text-[13px] text-muted-ink">
            Created{" "}
            {formatDateTime(report.created_at, {
              month: "short",
              day: "numeric",
            })}{" "}
            · Source {latest?.pdf_filename ?? "—"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="flat" size="sm" onClick={() => setRenaming(true)}>
            Rename
          </Button>
          <Button
            variant="danger-soft"
            size="sm"
            onClick={() => setDeleting(true)}
          >
            <Trash2 aria-hidden />
            Delete
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pickedRuns.length !== 2}
            onClick={() =>
              pickedRuns.length === 2 &&
              nav(
                `/reports/${report.id}/compare?a=${pickedRuns[1].run_id}&b=${pickedRuns[0].run_id}`,
              )
            }
          >
            <GitCompare aria-hidden />
            Compare
          </Button>
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            <FileUp aria-hidden />
            New version
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Latest status"
          value={
            latest ? (
              <RunStatusChip status={latest.status} size="lg" />
            ) : (
              "—"
            )
          }
          hint={latest ? `v${latest.version_number} · ${latest.kind}` : undefined}
        />
        <StatCard
          label="Coverage"
          value={coverage?.pct ?? "—"}
          hint={coverage?.detail}
        />
        <StatCard
          label="Versions"
          value={runs.length}
          hint={kinds || undefined}
        />
        <StatCard
          label="Last updated"
          value={
            latest
              ? formatDateTime(latest.uploaded_at, {
                  month: "short",
                  day: "numeric",
                })
              : "—"
          }
          hint={
            latest?.completed_at
              ? `v${latest.version_number} finished ${formatDateTime(latest.completed_at, { hour: "2-digit", minute: "2-digit" })}`
              : undefined
          }
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex items-center gap-2.5">
          <h2 className="text-[15px] font-semibold text-ink">Versions</h2>
          <span className="text-xs text-muted-ink">
            Select two versions to compare
          </span>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={pickedRuns.length !== 2}
          onClick={() =>
            pickedRuns.length === 2 &&
            nav(
              `/reports/${report.id}/compare?a=${pickedRuns[1].run_id}&b=${pickedRuns[0].run_id}`,
            )
          }
        >
          <GitCompare aria-hidden />
          Compare selected
        </Button>
      </div>

      <TableCard className="flex-none">
        <div className="overflow-x-auto">
          <Table className="min-w-[760px]">
            <THead>
              <tr>
                <Th className="w-9" />
                <Th className="w-14">Ver</Th>
                <Th className="w-[88px]">Kind</Th>
                <Th>PDF</Th>
                <Th className="w-[112px]">Status</Th>
                <Th className="w-[88px]">Findings</Th>
                <Th className="w-[124px]">Run</Th>
                <Th className="w-12" />
              </tr>
            </THead>
            <tbody>
              {runs.map((v) => (
                <tr
                  key={v.run_id}
                  className="cursor-pointer transition-colors hover:bg-soft/50"
                  onClick={() => nav(`/runs/${v.run_id}`)}
                >
                  <Td className="border-t-0" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={picked.has(v.run_id)}
                      aria-label={`Select v${v.version_number} for compare`}
                      onCheckedChange={(on) =>
                        setPicked((cur) => {
                          const next = new Set(cur);
                          if (on) {
                            // Two-slot compare: drop the oldest pick when full.
                            if (next.size >= 2) next.delete([...next][0]);
                            next.add(v.run_id);
                          } else next.delete(v.run_id);
                          return next;
                        })
                      }
                    />
                  </Td>
                  <Td>
                    <span className="font-semibold">v{v.version_number}</span>
                  </Td>
                  <Td>
                    <Chip>{v.kind}</Chip>
                  </Td>
                  <Td>
                    <div className="flex min-w-0 flex-col gap-px">
                      <span className="truncate">{v.pdf_filename}</span>
                      {v.status === "failed" && v.error ? (
                        <span className="truncate text-[11px] text-danger">
                          Error: {v.error}
                        </span>
                      ) : (
                        <span className="truncate text-[11px] text-muted-ink">
                          sha {v.pdf_sha256.slice(0, 4)}…
                          {v.pdf_sha256.slice(-3)}
                        </span>
                      )}
                    </div>
                  </Td>
                  <Td>
                    <RunStatusChip status={v.status} />
                  </Td>
                  <Td className="tabular-nums">
                    {findingsTotal(v) ?? "—"}
                  </Td>
                  <Td className="whitespace-nowrap text-muted-ink">
                    {formatDateTime(v.uploaded_at, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </Td>
                  <Td onClick={(e) => e.stopPropagation()}>
                    <KebabMenu
                      label={`Actions for v${v.version_number}`}
                      items={[
                        {
                          label: "Open findings",
                          icon: <Eye />,
                          onSelect: () => nav(`/runs/${v.run_id}`),
                        },
                        {
                          label: "Export coverage",
                          icon: <FileDown />,
                          onSelect: () =>
                            downloadFile(exportReportCoverageUrl(report.id)),
                        },
                        ...(v.status === "failed"
                          ? [
                              {
                                label: "Retry",
                                icon: <RotateCcw />,
                                onSelect: () => void doRetry(v),
                              },
                            ]
                          : []),
                        {
                          label: "Fork as new version",
                          icon: <GitFork />,
                          disabled: !TERMINAL.includes(v.status),
                          onSelect: () => void doFork(v),
                        },
                        {
                          label: "Delete version",
                          icon: <Trash2 />,
                          danger: true,
                          onSelect: () => setDeletingRun(v),
                        },
                      ]}
                    />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </TableCard>

      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a new report version PDF"
        className={cn(
          "flex min-h-24 shrink-0 flex-col items-center justify-center gap-2 rounded-2xl border bg-soft-2 px-4 py-3 text-center transition-colors",
          dragging
            ? "border-accent bg-accent-soft/40"
            : "border-line-strong hover:border-muted-ink/40",
          uploading && "pointer-events-none opacity-60",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) void doUpload(f);
        }}
        onClick={() => fileRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileRef.current?.click();
          }
        }}
      >
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void doUpload(f);
            e.target.value = "";
          }}
        />
        <span className="grid size-10 place-items-center rounded-full bg-accent-soft text-accent">
          <FilePlus className="size-5" aria-hidden />
        </span>
        <p className="text-sm font-medium text-ink">
          {uploading
            ? "Uploading…"
            : `Drop a new report PDF to create version v${nextVersion}`}
        </p>
        <p className="text-xs text-muted-ink">
          Same pipeline — extract, index, judge. New versions stay attached to
          this report.
        </p>
      </div>

      <RenameModal
        open={renaming}
        name={report.name}
        onClose={() => setRenaming(false)}
        onSaved={(name) => {
          setReport((r) => (r ? { ...r, name } : r));
          setRenaming(false);
          toast({ title: "Report renamed", message: `“${name}” saved.` });
        }}
        reportId={report.id}
      />

      <Modal
        open={deleting}
        onClose={() => setDeleting(false)}
        title="Delete report?"
        icon={
          <ModalIconTile tone="danger">
            <Trash2 />
          </ModalIconTile>
        }
        footer={
          <>
            <Button variant="flat" onClick={() => setDeleting(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={doDeleteReport}>
              <Trash2 aria-hidden />
              Delete report
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-ink">
          This will permanently delete{" "}
          <span className="font-medium text-ink">“{report.name}”</span> and all{" "}
          {runs.length} version{runs.length === 1 ? "" : "s"} — findings,
          corrections and their judge traces. This action cannot be undone.
        </p>
      </Modal>

      <Modal
        open={deletingRun !== null}
        onClose={() => setDeletingRun(null)}
        title={`Delete version v${deletingRun?.version_number}?`}
        icon={
          <ModalIconTile tone="danger">
            <Trash2 />
          </ModalIconTile>
        }
        footer={
          <>
            <Button variant="flat" onClick={() => setDeletingRun(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={doDeleteRun}>
              <Trash2 aria-hidden />
              Delete version
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-ink">
          This permanently deletes version v{deletingRun?.version_number} of “
          {report.name}” — its findings, corrections and judge traces. Other
          versions are unaffected.
        </p>
      </Modal>
    </div>
  );
}

function RenameModal({
  open,
  name,
  reportId,
  onClose,
  onSaved,
}: {
  open: boolean;
  name: string;
  reportId: string;
  onClose: () => void;
  onSaved: (name: string) => void;
}) {
  const [value, setValue] = useState(name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    if (open) {
      setValue(name);
      setError(null);
    }
  }, [open, name]);

  async function save() {
    const next = value.trim();
    if (!next) return;
    setBusy(true);
    setError(null);
    try {
      await renameReport(reportId, next);
      onSaved(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast({ title: "Rename failed", message: msg, variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Rename report"
      footer={
        <>
          <Button variant="flat" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy || !value.trim()}>
            <Check aria-hidden />
            Save
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
        className="flex flex-col gap-3.5"
      >
        <Field
          label="Report name"
          hint="Renaming doesn't affect versions, findings or exports."
        >
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
          />
        </Field>
        {error && (
          <p role="alert" className="text-[13px] text-danger">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
