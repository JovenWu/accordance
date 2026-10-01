import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getMeStats, listReports } from "@/api";
import { useAuth } from "@/auth/auth-context";
import { Avatar } from "@/components/ui/avatar";
import { Chip, RunStatusChip } from "@/components/ui/chip";
import { StatCard } from "@/components/ui/stat-card";
import { formatDateTime } from "@/lib/datetime";
import type { MeStats, ReportPage as ReportPageModel } from "@/types";

export function ProfilePage() {
  const { username, isAdmin } = useAuth();
  const [stats, setStats] = useState<MeStats | null>(null);
  const [reports, setReports] = useState<ReportPageModel | null>(null);

  useEffect(() => {
    getMeStats().then(setStats).catch(() => {});
    listReports({ limit: 50 }).then(setReports).catch(() => {});
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <div className="flex flex-col gap-0.5">
        <h1 className="text-[20px] font-semibold text-ink">Profile</h1>
        <p className="text-[13px] text-muted-ink">Your account and activity</p>
      </div>

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex w-full shrink-0 flex-col gap-4 lg:w-[420px]">
          <div className="flex flex-col gap-3 rounded-3xl bg-surface p-5">
            <div className="flex items-center gap-3">
              <Avatar name={username} className="size-12 text-base" />
              <div className="flex flex-col gap-0.5">
                <span className="text-[17px] font-semibold text-ink">
                  {username}
                </span>
                <span className="text-xs text-muted-ink">
                  {isAdmin ? "Admin account" : "Analyst account"}
                </span>
              </div>
              {isAdmin && <Chip tone="accent">Admin</Chip>}
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="My runs"
              value={stats ? String(stats.pdf_count) : "—"}
            />
            <StatCard
              label="Reports"
              value={reports ? String(reports.total) : "—"}
            />
            <StatCard
              label="Total spend"
              value={stats ? `$${stats.cost_usd.toFixed(2)}` : "—"}
            />
          </div>

          <h2 className="text-[15px] font-semibold text-ink">My reports</h2>
          <div className="max-h-[480px] min-h-0 flex-1 overflow-auto rounded-3xl bg-surface lg:max-h-none">
            <div className="min-w-[480px]">
              <div className="sticky top-0 z-10 flex h-[38px] items-center bg-soft-2 px-4 text-xs font-medium text-muted-ink">
                <span className="w-14 shrink-0">Vers.</span>
                <span className="min-w-0 flex-1">Report</span>
                <span className="w-[104px] shrink-0">Status</span>
                <span className="w-[110px] shrink-0">Updated</span>
              </div>
              {reports?.items.map((r) => (
                <Link
                  key={r.id}
                  to={`/reports/${r.id}`}
                  className="flex h-[46px] items-center border-b border-line px-4 transition-colors last:border-0 hover:bg-soft/50"
                >
                  <span className="w-14 shrink-0 text-[13px] font-semibold tabular-nums text-ink">
                    {r.latest.version_number}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                    {r.name}
                  </span>
                  <span className="w-[104px] shrink-0">
                    <RunStatusChip status={r.latest.status} />
                  </span>
                  <span className="w-[110px] shrink-0 text-[13px] text-muted-ink">
                    {formatDateTime(r.latest.uploaded_at, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </Link>
              ))}
              {reports?.items.length === 0 && (
                <p className="grid h-32 place-items-center text-[13px] text-muted-ink">
                  No reports yet — upload a PDF from Analyses.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
