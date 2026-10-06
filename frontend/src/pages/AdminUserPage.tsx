import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  KeyRound,
  ShieldOff,
  ShieldCheck,
  UserX,
  UserCheck,
} from "lucide-react";

import {
  adminGetUser,
  adminResetPassword,
  adminSetActive,
  adminSetAdmin,
  isNotFound,
} from "@/api";
import { useAuth } from "@/auth/auth-context";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Chip, RunStatusChip } from "@/components/ui/chip";
import { Field, Input } from "@/components/ui/input";
import { Modal, ModalIconTile } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat-card";
import { useToast } from "@/components/ui/toast";
import { formatDateTime, parseServerDate } from "@/lib/datetime";
import { NotFoundPage } from "@/pages/NotFoundPage";
import type { AdminUserDetail } from "@/types";

export function AdminUserPage() {
  const { id } = useParams<{ id: string }>();
  const { toast } = useToast();
  const { username: me } = useAuth();
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    adminGetUser(Number(id))
      .then((u) => {
        setUser(u);
        setError(null);
      })
      .catch((e) =>
        isNotFound(e)
          ? setMissing(true)
          : setError(e instanceof Error ? e.message : String(e)),
      );
  }, [id]);

  useEffect(load, [load]);

  async function patch(fn: () => Promise<unknown>, done: string) {
    if (!user) return;
    setBusy(true);
    try {
      await fn();
      toast(done, { message: user.username });
      load();
    } catch (e) {
      toast("Action failed", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  }

  if (missing) {
    return (
      <NotFoundPage
        title="User not found"
        message="That account doesn't exist or was removed."
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
  if (!user) {
    return (
      <div className="grid flex-1 place-items-center p-4 text-muted-ink sm:p-6 lg:p-10">
        Loading…
      </div>
    );
  }

  const isSelf = user.username === me;
  const lastActive = user.last_active
    ? formatDateTime(user.last_active, { dateStyle: "medium" })
    : "Never";
  const kindMax = Math.max(1, ...user.cost_by_kind.map((k) => k.cost_usd));
  const week = last7Days(user.daily_usage);
  const dayMax = Math.max(1, ...week.map((d) => d.cost_usd));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <Link
        to="/admin/users"
        className="flex w-fit items-center gap-1.5 text-[13px] text-muted-ink hover:text-ink"
      >
        <ArrowLeft className="size-4" aria-hidden />
        <span className="font-medium">Users</span>
        <span>/ {user.username}</span>
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Avatar name={user.username} className="size-10" />
          <div className="flex items-center gap-2.5">
            <h1 className="text-[20px] font-semibold text-ink">
              {user.username}
            </h1>
            {user.is_admin ? <Chip tone="accent">Admin</Chip> : <Chip>Analyst</Chip>}
            {user.is_active ? (
              <Chip tone="success">Active</Chip>
            ) : (
              <Chip>Disabled</Chip>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            icon={<KeyRound />}
            onClick={() => setResetOpen(true)}
          >
            Reset password
          </Button>
          <Button
            variant="outline"
            size="sm"
            icon={user.is_admin ? <ShieldOff /> : <ShieldCheck />}
            disabled={isSelf || busy}
            onClick={() =>
              void patch(
                () => adminSetAdmin(user.id, !user.is_admin),
                user.is_admin ? "Admin revoked" : "Admin granted",
              )
            }
          >
            {user.is_admin ? "Revoke admin" : "Make admin"}
          </Button>
          <Button
            variant="danger-soft"
            size="sm"
            icon={user.is_active ? <UserX /> : <UserCheck />}
            disabled={isSelf || busy}
            onClick={() =>
              void patch(
                () => adminSetActive(user.id, !user.is_active),
                user.is_active ? "Account disabled" : "Account enabled",
              )
            }
          >
            {user.is_active ? "Disable" : "Enable"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Runs" value={String(user.pdf_count)} hint="analyses run" />
        <StatCard
          label="Total spend"
          value={`$${user.cost_usd.toFixed(2)}`}
          hint="all time"
        />
        <StatCard label="Last active" value={lastActive} hint="most recent run" />
        <StatCard
          label="Member since"
          value={formatDateTime(user.created_at, {
            month: "short",
            year: "numeric",
          })}
          hint="account created"
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-h-0 flex-1 flex-col gap-3 lg:h-full">
          <h2 className="text-[15px] font-semibold text-ink">Recent runs</h2>
          <div className="max-h-[480px] min-h-0 flex-1 overflow-auto rounded-3xl bg-surface lg:max-h-none">
            <div className="min-w-[480px]">
              <div className="sticky top-0 z-10 flex h-[38px] items-center bg-soft-2 px-4 text-xs font-medium text-muted-ink">
                <span className="min-w-0 flex-1">PDF</span>
                <span className="w-[104px] shrink-0">Status</span>
                <span className="w-20 shrink-0">Cost</span>
                <span className="w-[110px] shrink-0">Date</span>
              </div>
              {user.recent_runs.map((r) => (
                <div
                  key={r.id}
                  className="flex h-[46px] items-center border-b border-line px-4 last:border-0"
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                    {r.pdf_filename}
                  </span>
                  <span className="w-[104px] shrink-0">
                    <RunStatusChip status={r.status} />
                  </span>
                  <span className="w-20 shrink-0 text-[13px] tabular-nums text-ink">
                    ${r.run_cost_usd.toFixed(2)}
                  </span>
                  <span className="w-[110px] shrink-0 text-[13px] text-muted-ink">
                    {formatDateTime(r.uploaded_at, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
              ))}
              {user.recent_runs.length === 0 && (
                <p className="grid h-32 place-items-center text-[13px] text-muted-ink">
                  No runs yet.
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-4 lg:w-[360px]">
          <div className="flex flex-col gap-2.5 rounded-3xl bg-surface p-4">
            <span className="text-xs font-medium text-muted-ink">
              Spend by run kind
            </span>
            {user.cost_by_kind.map((k) => (
              <div key={k.kind} className="flex items-center gap-2.5">
                <span className="w-[52px] shrink-0 text-xs text-muted-ink">
                  {k.kind}
                </span>
                <span className="h-2 flex-1 overflow-hidden rounded bg-soft-2">
                  <span
                    className="block h-full bg-accent"
                    style={{ width: `${(k.cost_usd / kindMax) * 100}%` }}
                  />
                </span>
                <span className="text-xs font-medium tabular-nums text-ink">
                  ${k.cost_usd.toFixed(2)}
                </span>
              </div>
            ))}
            {user.cost_by_kind.length === 0 && (
              <span className="text-xs text-muted-ink">No spend yet.</span>
            )}
          </div>
          <div className="flex flex-col gap-2.5 rounded-3xl bg-surface p-4">
            <span className="text-xs font-medium text-muted-ink">
              Daily usage — last 7 days
            </span>
            <div className="flex h-24 items-end gap-2">
              {week.map((d) => (
                <div
                  key={d.day}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-1.5"
                  title={`${d.day}: $${d.cost_usd.toFixed(2)} · ${d.pdf_count} PDFs`}
                >
                  <span
                    className="w-full rounded-[3px] bg-accent"
                    style={{
                      height: `${Math.max(3, (d.cost_usd / dayMax) * 100)}%`,
                    }}
                  />
                  <span className="text-[10px] text-muted-ink">
                    {"SMTWTFS"[parseServerDate(d.day).getUTCDay()]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <ResetPasswordModal
        open={resetOpen}
        username={user.username}
        userId={user.id}
        onClose={() => setResetOpen(false)}
      />
    </div>
  );
}

function last7Days(daily: { day: string; cost_usd: number; pdf_count: number }[]) {
  const byDay = new Map(daily.map((d) => [d.day, d]));
  const out: { day: string; cost_usd: number; pdf_count: number }[] = [];
  const today = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400000);
    const key = d.toISOString().slice(0, 10);
    out.push(byDay.get(key) ?? { day: key, cost_usd: 0, pdf_count: 0 });
  }
  return out;
}

function ResetPasswordModal({
  open,
  username,
  userId,
  onClose,
}: {
  open: boolean;
  username: string;
  userId: number;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function reset() {
    setBusy(true);
    try {
      await adminResetPassword(userId, password);
      toast("Password reset", { message: `New password set for ${username}` });
      setPassword("");
      onClose();
    } catch (e) {
      toast("Reset failed", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reset password"
      icon={
        <ModalIconTile tone="warning">
          <KeyRound aria-hidden />
        </ModalIconTile>
      }
      footer={
        <>
          <Button variant="flat" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            icon={<KeyRound />}
            busy={busy}
            disabled={password.length < 8}
            onClick={() => void reset()}
          >
            Reset password
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-muted-ink">
          Set a new temporary password for {username}.
        </p>
        <Field label="New password" hint="At least 8 characters.">
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            className="w-full max-w-[280px]"
          />
        </Field>
      </div>
    </Modal>
  );
}
