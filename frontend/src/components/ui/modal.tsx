import * as React from "react";
import { X } from "lucide-react";

import { useModalA11y } from "@/lib/useModalA11y";
import { cn } from "@/lib/utils";

export function Modal({
  open,
  title,
  icon,
  onClose,
  children,
  footer,
  className,
}: {
  open: boolean;
  title: React.ReactNode;
  /** Optional tinted tile shown left of the title (e.g. trash icon). */
  icon?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  const panelRef = useModalA11y<HTMLDivElement>(open, onClose);
  const titleId = React.useId();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-dim p-4 animate-in fade-in-0 [--tw-duration:150ms]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "w-[540px] max-w-[92vw] rounded-3xl bg-surface shadow-modal outline-none animate-in fade-in-0 zoom-in-95 [--tw-duration:150ms]",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 pt-[18px]">
          <div className="flex items-center gap-2.5">
            {icon}
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {title}
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid size-6 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
        <div className="px-6 pb-5 pt-3.5">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2.5 px-6 pb-5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/** Small tinted square holding a modal header icon. */
export function ModalIconTile({
  tone = "accent",
  children,
}: {
  tone?: "accent" | "danger" | "warning" | "neutral";
  children: React.ReactNode;
}) {
  const tones = {
    accent: "bg-accent-soft text-accent",
    danger: "bg-danger-soft text-danger",
    warning: "bg-warning-soft text-warning",
    neutral: "bg-soft text-ink",
  };
  return (
    <span
      className={cn(
        "grid size-8 place-items-center rounded-lg [&_svg]:size-4",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
