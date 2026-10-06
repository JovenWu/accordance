import * as React from "react";
import { CircleCheck, TriangleAlert, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type ToastVariant = "success" | "error";
export interface ToastOptions {
  variant?: ToastVariant;
  message?: string;
}
export interface ToastArgs {
  title: string;
  message?: string;
  variant?: ToastVariant;
}

interface ToastItem {
  id: number;
  title: string;
  message?: string;
  variant: ToastVariant;
}

interface ToastCtx {
  toast: (
    title: string | ToastArgs,
    options?: ToastOptions | ToastVariant,
  ) => void;
}
const Ctx = React.createContext<ToastCtx | null>(null);

export function useToast(): ToastCtx {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const nextId = React.useRef(1);

  const toast = React.useCallback(
    (
      titleOrArgs: string | ToastArgs,
      options?: ToastOptions | ToastVariant,
    ) => {
      const base: ToastArgs =
        typeof titleOrArgs === "string"
          ? { title: titleOrArgs }
          : titleOrArgs;
      const opts: ToastOptions =
        typeof options === "string" ? { variant: options } : (options ?? {});
      const variant = opts.variant ?? base.variant ?? "success";
      const message = opts.message ?? base.message;
      const id = nextId.current++;
      setItems((cur) => [
        ...cur,
        { id, title: base.title, message, variant },
      ]);
      setTimeout(() => {
        setItems((cur) => cur.filter((t) => t.id !== id));
      }, 5000);
    },
    [],
  );

  const value = React.useMemo(() => ({ toast }), [toast]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-5 right-5 z-[70] flex w-[400px] max-w-[92vw] flex-col gap-2.5"
        role="region"
        aria-label="Notifications"
      >
        {items.map((t) => (
          <ToastCard
            key={t.id}
            item={t}
            onDismiss={() =>
              setItems((cur) => cur.filter((x) => x.id !== t.id))
            }
          />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: () => void;
}) {
  const ok = item.variant === "success";
  return (
    <div
      role={ok ? "status" : "alert"}
      className="pointer-events-auto flex items-center gap-2.5 rounded-xl bg-surface px-3.5 py-3 shadow-modal animate-in fade-in-0 slide-in-from-bottom-2 [--tw-duration:200ms]"
    >
      <span
        className={cn(
          "grid size-7 shrink-0 place-items-center rounded-lg [&_svg]:size-4",
          ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger",
        )}
      >
        {ok ? <CircleCheck aria-hidden /> : <TriangleAlert aria-hidden />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold text-ink">
          {item.title}
        </span>
        {item.message && (
          <span className="block truncate text-xs text-muted-ink">
            {item.message}
          </span>
        )}
      </span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className="grid size-6 shrink-0 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}
