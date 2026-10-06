import { useEffect, useState } from "react";
import { LayoutList, LogOut, Menu, Users, X } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { getMeStats } from "@/api";
import { useAuth } from "@/auth/auth-context";
import { BrandMark } from "@/components/BrandMark";
import { Avatar } from "@/components/ui/avatar";
import { useToast } from "@/components/ui/toast";
import { useModalA11y } from "@/lib/useModalA11y";
import { cn } from "@/lib/utils";
import { formatCost } from "@/lib/cost";
import type { MeStats } from "@/types";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex h-9 w-full items-center gap-3 rounded-2xl px-2 text-sm transition-colors",
    isActive ? "bg-soft text-ink" : "text-ink hover:bg-soft/60",
  );

export function AppShell() {
  const [navOpen, setNavOpen] = useState(false);
  const closeNav = () => setNavOpen(false);
  const drawerRef = useModalA11y<HTMLDivElement>(navOpen, closeNav);

  return (
    <div className="flex h-screen min-h-0 w-full flex-col bg-page lg:flex-row">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 lg:hidden">
        <button
          type="button"
          aria-label="Open navigation"
          onClick={() => setNavOpen(true)}
          className="grid size-8 place-items-center rounded-xl text-ink transition-colors hover:bg-soft"
        >
          <Menu className="size-5" aria-hidden />
        </button>
        <Link
          to="/"
          aria-label="Accordance home"
          className="flex items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <BrandMark className="size-7 rounded-[8px]" />
          <span className="text-[15px] font-semibold text-ink">Accordance</span>
        </Link>
      </header>

      <aside className="hidden h-full w-[264px] shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <SidebarNav />
      </aside>

      {navOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-dim-deep animate-in fade-in-0 [--tw-duration:150ms]"
            onClick={closeNav}
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 flex w-64 flex-col bg-surface shadow-drawer outline-none animate-in slide-in-from-left [--tw-duration:200ms]"
          >
            <button
              type="button"
              aria-label="Close navigation"
              onClick={closeNav}
              className="absolute right-4 top-6 z-10 grid size-6 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2"
            >
              <X className="size-3.5" aria-hidden />
            </button>
            <SidebarNav onNavigate={closeNav} />
          </div>
        </div>
      )}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { username, isAdmin, logout } = useAuth();
  const { toast } = useToast();
  const [stats, setStats] = useState<MeStats | null>(null);

  useEffect(() => {
    getMeStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  return (
    <>
      <Link
        to="/"
        className="flex items-center gap-3 p-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        aria-label="Accordance home"
        onClick={onNavigate}
      >
        <BrandMark className="size-[34px] rounded-[10px]" />
        <span className="flex flex-col gap-px">
          <span className="text-[17px] font-semibold leading-tight text-ink">
            Accordance
          </span>
          <span className="text-[11px] text-muted-ink">
            GRI disclosure analysis
          </span>
        </span>
      </Link>

      <nav className="flex flex-col gap-0.5 px-3 py-1" aria-label="Main">
        <NavLink to="/" end className={linkClass} onClick={onNavigate}>
          <LayoutList className="size-[18px]" aria-hidden />
          Analyses
        </NavLink>
        {isAdmin && (
          <NavLink
            to="/admin/users"
            className={linkClass}
            onClick={onNavigate}
          >
            <Users className="size-[18px]" aria-hidden />
            Users
          </NavLink>
        )}
      </nav>

      <div className="flex-1" />

      <div className="flex items-center gap-2.5 border-t border-line p-4">
        <Link
          to="/profile"
          className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label="Open profile"
          onClick={onNavigate}
        >
          <Avatar name={username} />
          <span className="flex min-w-0 flex-col gap-px text-left">
            <span className="truncate text-sm font-medium text-ink">
              {username}
            </span>
            <span className="truncate text-[11px] text-muted-ink">
              {stats
                ? `${stats.pdf_count} ${stats.pdf_count === 1 ? "analysis" : "analyses"} · ${formatCost(stats.cost_usd)}`
                : " "}
            </span>
          </span>
        </Link>
        <button
          type="button"
          aria-label="Log out"
          title="Log out"
          onClick={() =>
            logout().catch(() =>
              toast({ title: "Logout failed", variant: "error" }),
            )
          }
          className="grid size-8 shrink-0 place-items-center rounded-full text-muted-ink transition-colors hover:bg-soft hover:text-ink"
        >
          <LogOut className="size-4" aria-hidden />
        </button>
      </div>
    </>
  );
}
