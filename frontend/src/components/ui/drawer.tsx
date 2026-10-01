import * as React from "react";
import { X } from "lucide-react";

import { useModalA11y } from "@/lib/useModalA11y";
import { cn } from "@/lib/utils";

/** Right-edge overlay drawer (corrections, traces) — 420–440px per design. */
export function Drawer({
  open,
  title,
  subtitle,
  onClose,
  children,
  className,
}: {
  open: boolean;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  const panelRef = useModalA11y<HTMLDivElement>(open, onClose);
  const titleId = React.useId();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 bg-dim animate-in fade-in-0 [--tw-duration:150ms]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "absolute right-0 top-0 flex h-full w-[420px] max-w-[94vw] flex-col bg-surface shadow-drawer outline-none animate-in slide-in-from-right-4 [--tw-duration:200ms]",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-5 pb-3.5 pt-[18px]">
          <div className="flex flex-col gap-0.5">
            <h2 id={titleId} className="text-[15px] font-semibold text-ink">
              {title}
            </h2>
            {subtitle && <p className="text-[11px] text-muted-ink">{subtitle}</p>}
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid size-6 shrink-0 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
        <div className="h-px w-full shrink-0 bg-line" />
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
