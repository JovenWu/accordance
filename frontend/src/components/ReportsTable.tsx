import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, FileSearch, FileDown, Trash2 } from "lucide-react";

import { deleteReport, exportReportCoverageUrl, listReports } from "@/api";
import { downloadFile } from "@/api";
import { KebabMenu } from "@/components/ui/menu";
import { Modal, ModalIconTile } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { RunStatusChip } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TableCard, Table, THead, Th, Td } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { formatDateTime } from "@/lib/datetime";
import type { ReportPage, ReportSummary, RunStatus } from "@/types";

export const PAGE_SIZE = 10;
const TERMINAL: RunStatus[] = ["completed", "failed", "cancelled"];

function kindLabel(kind: string): string {
  return kind === "initial" ? "initial" : kind;
}

function findingsSummary(r: ReportSummary): string | null {
  const c = r.latest.counts;
  const cov = c.covered ?? 0;
  const part = c.partial ?? 0;
  const miss = c.missing ?? 0;
  if (cov + part + miss === 0) return null;
  return `${cov} cov · ${part} part · ${miss} miss`;
}

export function ReportsTable({ query }: { query: string }) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ReportPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ReportSummary | null>(null);
  const nav = useNavigate();
  const { toast } = useToast();
  const seq = useRef(0);

  const load = useCallback(async (q: string, p: number) => {
    const mySeq = ++seq.current;
    try {
      const d = await listReports({ q, limit: PAGE_SIZE, offset: p * PAGE_SIZE });
      if (seq.current === mySeq) {
        setData(d);
        setError(null);
      }
      return d;
    } catch (e) {
      if (seq.current === mySeq)
        setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  // Reset to page 0 when the search changes; refetch.
  useEffect(() => {
    setPage(0);
    void load(query, 0);
  }, [query, load]);

  useEffect(() => {
    void load(query, page);
  }, [page, query, load]);

  // Poll while any visible report has a non-terminal latest run.
  useEffect(() => {
    const active = data?.items.some((r) => !TERMINAL.includes(r.latest.status));
    if (!active) return;
    const t = setInterval(() => void load(query, page), 5000);
    return () => clearInterval(t);
  }, [data, query, page, load]);

  async function confirmDelete() {
    if (!deleting) return;
    const rep = deleting;
    try {
      await deleteReport(rep.id);
      setDeleting(null);
      toast({ title: "Report deleted", message: `“${rep.name}” removed.` });
      void load(query, page);
    } catch (e) {
      toast({
        title: "Delete failed",
        message: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 0;

  return (
    <TableCard>
      <div className="min-h-0 flex-1 overflow-auto">
        <Table className="min-w-[720px]">
          <THead>
            <tr>
              <Th>Report</Th>
              <Th className="w-[90px]">Latest</Th>
              <Th className="w-[112px]">Status</Th>
              <Th className="w-[230px]">Findings</Th>
              <Th className="w-[64px]">Vers.</Th>
              <Th className="w-[132px]">Updated</Th>
              <Th className="w-[48px]" />
            </tr>
          </THead>
          <tbody>
            {data === null && !error
              ? Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <Td colSpan={7} className="border-t-0">
                      <Skeleton className="h-8 w-full" />
                    </Td>
                  </tr>
                ))
              : data?.items.map((r) => (
                  <tr
                    key={r.id}
                    className="cursor-pointer transition-colors hover:bg-soft/50"
                    onClick={() => nav(`/reports/${r.id}`)}
                  >
                    <Td>
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <Link
                          to={`/reports/${r.id}`}
                          className="truncate text-[13px] font-medium text-ink hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {r.name}
                        </Link>
                        <span className="truncate text-[11px] text-muted-ink">
                          {r.latest.pdf_filename} · v
                          {r.latest.version_number}
                        </span>
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap text-muted-ink">
                      v{r.latest.version_number} ·{" "}
                      {kindLabel(r.latest.kind)}
                    </Td>
                    <Td>
                      <RunStatusChip status={r.latest.status} />
                    </Td>
                    <Td className="whitespace-nowrap text-muted-ink">
                      {findingsSummary(r) ?? "—"}
                    </Td>
                    <Td className="tabular-nums">{r.version_count}</Td>
                    <Td className="whitespace-nowrap text-muted-ink">
                      {formatDateTime(r.latest.uploaded_at, {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </Td>
                    <Td onClick={(e) => e.stopPropagation()}>
                      <KebabMenu
                        label={`Actions for ${r.name}`}
                        items={[
                          {
                            label: "Open report",
                            icon: <ArrowRight />,
                            onSelect: () => nav(`/reports/${r.id}`),
                          },
                          {
                            label: "Export coverage",
                            icon: <FileDown />,
                            onSelect: () =>
                              downloadFile(exportReportCoverageUrl(r.id)),
                          },
                          {
                            label: "Delete report",
                            icon: <Trash2 />,
                            danger: true,
                            onSelect: () => setDeleting(r),
                          },
                        ]}
                      />
                    </Td>
                  </tr>
                ))}
          </tbody>
        </Table>

        {error && (
          <div className="grid place-items-center gap-2 p-4 sm:p-6 lg:p-10">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        {data && data.items.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center gap-2.5 p-4 text-center sm:p-6 lg:p-10">
            <span className="grid size-14 place-items-center rounded-2xl bg-soft-2 text-muted-ink">
              <FileSearch className="size-7" aria-hidden />
            </span>
            <p className="text-base font-semibold text-ink">
              {query ? "No reports match your search" : "No reports yet"}
            </p>
            <p className="text-[13px] text-muted-ink">
              {query
                ? `Nothing matches “${query}”.`
                : "Upload a sustainability report above to run your first GRI analysis."}
            </p>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line bg-soft-2 px-4 py-2.5">
        <Pagination
          page={page}
          pageCount={pageCount}
          total={data?.total ?? 0}
          pageItemCount={data?.items.length ?? 0}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>

      <Modal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete report?"
        icon={
          <ModalIconTile tone="danger">
            <Trash2 />
          </ModalIconTile>
        }
        footer={
          <>
            <Button variant="flat" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={confirmDelete}>
              <Trash2 aria-hidden />
              Delete report
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-ink">
          This will permanently delete{" "}
          <span className="font-medium text-ink">“{deleting?.name}”</span> and
          all {deleting?.version_count} version
          {deleting && deleting.version_count === 1 ? "" : "s"} — findings,
          corrections and their judge traces. This action cannot be undone.
        </p>
      </Modal>
    </TableCard>
  );
}
