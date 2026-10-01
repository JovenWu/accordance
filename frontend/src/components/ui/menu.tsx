import * as React from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";

export interface MenuItem {
  label: string;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

const MARGIN = 8; // minimum distance from any viewport edge
const GAP = 4; // trigger → popover spacing (was `top-9` on the size-8 button)

const itemEls = (menu: HTMLDivElement | null) =>
  Array.from(
    menu?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [],
  );

/** 32px circular kebab button opening a small dropdown menu. The popover is
 * portaled to <body> and positioned with `fixed` so `overflow-hidden`/`auto`
 * ancestors (table cards, scrollers) can't clip it. */
export function KebabMenu({
  items,
  label = "Actions",
  align = "end",
}: {
  items: MenuItem[];
  label?: string;
  align?: "start" | "end";
}) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const triggerId = React.useId();
  const focusLastRef = React.useRef(false);

  const close = React.useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  // Writes top/left straight onto the portal node — no state, no re-render.
  const place = React.useCallback(() => {
    const trigger = triggerRef.current;
    const menu = menuRef.current;
    if (!trigger || !menu) return;
    const r = trigger.getBoundingClientRect();
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    const left = Math.min(
      Math.max(align === "end" ? r.right - mw : r.left, MARGIN),
      window.innerWidth - mw - MARGIN,
    );
    let top = r.bottom + GAP;
    if (top + mh > window.innerHeight - MARGIN && r.top - GAP - mh >= MARGIN)
      top = r.top - GAP - mh; // flip above the trigger when there's no room below
    top = Math.max(MARGIN, Math.min(top, window.innerHeight - MARGIN - mh));
    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;
  }, [align]);

  // Position + focus the first (or last, for ArrowUp-open) item before paint.
  React.useLayoutEffect(() => {
    if (!open) return;
    place();
    const els = itemEls(menuRef.current);
    els[focusLastRef.current ? els.length - 1 : 0]?.focus();
    focusLastRef.current = false;
  }, [open, place]);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t))
        return;
      setOpen(false); // pointer dismissal lets focus land where the user clicked
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // don't let an enclosing modal/drawer also close
      close();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true); // capture: nested scrollers
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, close, place]);

  const onTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      focusLastRef.current = e.key === "ArrowUp";
      setOpen(true);
    }
  };

  const onMenuKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Tab") {
      // Close without trapping: park focus on the trigger so the default Tab
      // order continues from the element after it.
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    const els = itemEls(menuRef.current);
    const i = els.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      els[(i + 1) % els.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      els[(i - 1 + els.length) % els.length]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      els[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      els[els.length - 1]?.focus();
    }
  };

  return (
    <div>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        className="grid size-8 place-items-center rounded-full bg-soft text-ink transition-colors hover:bg-soft-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
      >
        <MoreHorizontal className="size-4" aria-hidden />
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-labelledby={triggerId}
            onKeyDown={onMenuKeyDown}
            style={{ top: 0, left: 0 }}
            className="fixed z-50 min-w-[168px] rounded-xl border border-line bg-surface p-1 shadow-modal animate-in fade-in-0 zoom-in-95 [--tw-duration:100ms]"
          >
            {items.map((item) => (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                aria-disabled={item.disabled || undefined}
                onClick={() => {
                  if (item.disabled) return;
                  close();
                  item.onSelect();
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] font-medium transition-colors focus-visible:outline-none aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:size-3.5",
                  item.danger
                    ? "text-danger hover:bg-danger-soft focus:bg-danger-soft"
                    : "text-ink hover:bg-soft focus:bg-soft",
                )}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
