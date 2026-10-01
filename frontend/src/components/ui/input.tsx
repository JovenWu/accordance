import * as React from "react";
import { ChevronDown, Search } from "lucide-react";

import { cn } from "@/lib/utils";

const fieldClass =
  "w-full rounded-xl border border-line bg-surface px-3 text-sm text-ink shadow-field transition-colors placeholder:text-muted-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:border-accent disabled:cursor-not-allowed disabled:opacity-50";

const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    ref={ref}
    className={cn("flex h-10", fieldClass, className)}
    {...props}
  />
));
Input.displayName = "Input";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn("flex min-h-[80px] py-2", fieldClass, className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className={cn("relative", className)}>
    <select
      ref={ref}
      className={cn(
        "h-9 w-full cursor-pointer appearance-none pr-8",
        fieldClass,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown
      className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-ink"
      aria-hidden
    />
  </div>
));
Select.displayName = "Select";

/** Label + control + optional hint, matching the modal form rows. */
export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const id = React.useId();
  const child = React.isValidElement(children)
    ? React.cloneElement(
        children as React.ReactElement<{ id?: string }>,
        { id },
      )
    : children;
  return (
    <div className={cn("flex w-full flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      {child}
      {hint && <p className="px-1 text-xs text-muted-ink">{hint}</p>}
    </div>
  );
}

/** Compact toolbar search box — icon + borderless input in a white group. */
export function SearchInput({
  className,
  inputProps,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  inputProps?: React.InputHTMLAttributes<HTMLInputElement>;
}) {
  return (
    <div
      className={cn(
        "flex h-9 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 shadow-field focus-within:ring-2 focus-within:ring-accent/40",
        className,
      )}
      {...props}
    >
      <Search className="size-4 shrink-0 text-muted-ink" aria-hidden />
      <input
        type="search"
        aria-label="Search"
        className="w-full bg-transparent text-sm text-ink placeholder:text-muted-ink focus-visible:outline-none [&::-webkit-search-cancel-button]:hidden"
        {...inputProps}
      />
    </div>
  );
}

export { Input, Textarea, Select, fieldClass };
