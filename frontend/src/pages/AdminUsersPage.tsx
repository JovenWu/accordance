import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Eye,
  Power,
  ShieldCheck,
  ShieldOff,
  UserPlus,
  UserRound,
} from "lucide-react";

import {
  adminCreateUser,
  adminListUsers,
  adminSetActive,
  adminSetAdmin,
} from "@/api";
import { useAuth } from "@/auth/auth-context";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Field, Input } from "@/components/ui/input";
import { KebabMenu } from "@/components/ui/menu";
import { Modal, ModalIconTile } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { formatDateTime } from "@/lib/datetime";
import type { AdminUser } from "@/types";

export function AdminUsersPage() {
  const { toast } = useToast();
  const { username: me } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(() => {
    adminListUsers()
      .then((u) => {
        setUsers(u);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(load, [load]);

  async function patch(
    user: AdminUser,
    fn: () => Promise<AdminUser>,
    done: string,
  ) {
    try {
      await fn();
      toast(done, { message: user.username });
      load();
    } catch (e) {
      toast("Action failed", {
        variant: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pb-6 pt-4 sm:px-6 lg:px-8 lg:pb-8 lg:pt-5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-[20px] font-semibold text-ink">Users</h1>
          <p className="text-[13px] text-muted-ink">
            {users ? `${users.length} accounts` : "…"} · admin view
          </p>
        </div>
        <Button
          size="sm"
          icon={<UserPlus />}
          onClick={() => setCreateOpen(true)}
        >
          Create user
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto rounded-3xl bg-surface">
        <div className="min-w-[640px]">
          <div className="sticky top-0 z-10 flex h-10 items-center bg-soft-2 px-4 text-xs font-medium text-muted-ink">
            <span className="min-w-0 flex-1">User</span>
            <span className="w-24 shrink-0">Role</span>
            <span className="w-[100px] shrink-0">Status</span>
            <span className="w-[84px] shrink-0">Runs</span>
            <span className="w-[84px] shrink-0">Spend</span>
            <span className="w-28 shrink-0">Joined</span>
            <span className="w-11 shrink-0" />
          </div>
          {error && (
            <p className="grid h-40 place-items-center text-sm text-danger">
              {error}
            </p>
          )}
          {!error && users === null && (
            <p className="grid h-40 place-items-center text-sm text-muted-ink">
              Loading…
            </p>
          )}
          {users?.map((u) => (
            <div
              key={u.id}
              className="flex h-14 items-center border-b border-line px-4 last:border-0"
            >
              <div className="flex min-w-0 flex-1 items-center gap-2.5">
                <Avatar name={u.username} className="size-10" />
                <span className="truncate text-[13px] font-medium text-ink">
                  {u.username}
                </span>
              </div>
              <span className="w-24 shrink-0">
                {u.is_admin ? (
                  <Chip tone="accent">Admin</Chip>
                ) : (
                  <Chip>Analyst</Chip>
                )}
              </span>
              <span className="w-[100px] shrink-0">
                {u.is_active ? (
                  <Chip tone="success">Active</Chip>
                ) : (
                  <Chip>Disabled</Chip>
                )}
              </span>
              <span className="w-[84px] shrink-0 text-[13px] tabular-nums text-ink">
                {u.pdf_count}
              </span>
              <span className="w-[84px] shrink-0 text-[13px] tabular-nums text-ink">
                ${u.cost_usd.toFixed(2)}
              </span>
              <span className="w-28 shrink-0 text-[13px] text-muted-ink">
                {formatDateTime(u.created_at, {
                  month: "short",
                  year: "numeric",
                })}
              </span>
              <span className="flex w-11 shrink-0 justify-center">
                <KebabMenu
                  label={`Actions for ${u.username}`}
                  items={[
                    {
                      label: "View details",
                      icon: <Eye />,
                      onSelect: () => navigate(`/admin/users/${u.id}`),
                    },
                    {
                      label: u.is_admin ? "Revoke admin" : "Make admin",
                      icon: u.is_admin ? <ShieldOff /> : <ShieldCheck />,
                      disabled: u.username === me,
                      onSelect: () =>
                        void patch(
                          u,
                          () => adminSetAdmin(u.id, !u.is_admin),
                          u.is_admin ? "Admin revoked" : "Admin granted",
                        ),
                    },
                    {
                      label: u.is_active ? "Disable" : "Enable",
                      icon: <Power />,
                      danger: u.is_active,
                      disabled: u.username === me,
                      onSelect: () =>
                        void patch(
                          u,
                          () => adminSetActive(u.id, !u.is_active),
                          u.is_active
                            ? "Account disabled"
                            : "Account enabled",
                        ),
                    },
                  ]}
                />
              </span>
            </div>
          ))}
          {users?.length === 0 && (
            <p className="grid h-40 place-items-center text-sm text-muted-ink">
              No users yet.
            </p>
          )}
        </div>
      </div>

      <CreateUserModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          load();
        }}
      />
    </div>
  );
}

function CreateUserModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { toast } = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    try {
      await adminCreateUser(username.trim(), password);
      toast("User created", { message: username.trim() });
      setUsername("");
      setPassword("");
      onCreated();
    } catch (e) {
      toast("Could not create user", {
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
      title="Create user"
      icon={
        <ModalIconTile>
          <UserRound aria-hidden />
        </ModalIconTile>
      }
      footer={
        <>
          <Button variant="flat" onClick={onClose}>
            Cancel
          </Button>
          <Button
            icon={<UserPlus />}
            busy={busy}
            disabled={!username.trim() || password.length < 8}
            onClick={() => void create()}
          >
            Create user
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3.5">
        <Field label="Username">
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="a.wibowo"
            autoComplete="off"
          />
        </Field>
        <Field
          label="Temporary password"
          hint="At least 8 characters — share it with the user."
        >
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••••••"
            autoComplete="new-password"
          />
        </Field>
      </div>
    </Modal>
  );
}
