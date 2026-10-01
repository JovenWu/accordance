import { cn } from "@/lib/utils";

export function initialsOf(username: string): string {
  const parts = username.split(/[.\s_-]+/).filter(Boolean);
  const letters =
    parts.length >= 2
      ? parts[0][0] + parts[parts.length - 1][0]
      : username.slice(0, 2);
  return letters.toUpperCase();
}

export function Avatar({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid size-9 shrink-0 place-items-center rounded-full bg-soft text-sm font-medium text-ink",
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}
