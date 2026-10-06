import * as React from "react";
import { Check, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

export interface CheckboxProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked?: boolean;
  /** true → dash; false/undefined → unchecked. */
  indeterminate?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

/** 16px rounded checkbox matching the scope/export rows. */
export const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ className, indeterminate, onCheckedChange, checked, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : !!checked}
      onClick={() => onCheckedChange?.(!checked)}
      className={cn(
        "grid size-4 shrink-0 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
        checked || indeterminate
          ? "bg-accent text-accent-ink"
          : "border border-line-strong bg-surface",
        className,
      )}
      {...props}
    >
      {indeterminate ? (
        <Minus className="size-3" strokeWidth={3} aria-hidden />
      ) : checked ? (
        <Check className="size-3" strokeWidth={3} aria-hidden />
      ) : null}
    </button>
  ),
);
Checkbox.displayName = "Checkbox";
