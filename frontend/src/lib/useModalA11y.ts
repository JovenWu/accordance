import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])';

/**
 * Wires up baseline modal accessibility for an open overlay:
 *  - Escape closes it
 *  - focus moves into the panel when it opens
 *  - Tab/Shift-Tab wraps around the panel's focusable elements (focus trap)
 *  - focus returns to the previously-focused element when it closes
 *
 * Returns a ref to attach to the focusable panel container (give it
 * `tabIndex={-1}` plus `role="dialog"`/`aria-modal`). `onClose` is read through
 * a ref so the effect captures the prior focus only once per open, not on every
 * render.
 */
export function useModalA11y<T extends HTMLElement = HTMLElement>(
  open: boolean,
  onClose: () => void,
) {
  const panelRef = useRef<T>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const restore = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const els = panel.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (els.length === 0) {
        e.preventDefault();
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      const active = document.activeElement;
      const inside = active !== null && panel.contains(active);
      // Wrap at the edges; `active === panel` covers Shift-Tab leaving the
      // tabIndex=-1 container itself.
      const wrapTo = e.shiftKey
        ? !inside || active === first || active === panel
          ? last
          : null
        : !inside || active === last
          ? first
          : null;
      if (wrapTo) {
        e.preventDefault();
        wrapTo.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restore?.focus?.();
    };
  }, [open]);

  return panelRef;
}
