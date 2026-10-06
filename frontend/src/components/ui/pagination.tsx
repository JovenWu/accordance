import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { itemRange, paginationItems } from "@/lib/pagination";

export function Pagination({
  page,
  pageCount,
  total,
  pageItemCount,
  pageSize,
  onPageChange,
  itemNoun = "report",
  className,
}: {
  page: number;
  pageCount: number;
  total: number;
  pageItemCount: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  itemNoun?: string;
  className?: string;
}) {
  const current = page + 1;
  const items = paginationItems(current, pageCount);
  const { from, to } = itemRange(page * pageSize, pageItemCount, total);

  return (
    <nav
      aria-label="Pagination"
      className={cn("flex items-center justify-between gap-3", className)}
    >
      <p role="status" className="text-[13px] text-muted-ink">
        {total === 0 ? (
          <>No {itemNoun}s</>
        ) : (
          <>
            <span className="tabular-nums">{from}</span>–
            <span className="tabular-nums">{to}</span> of{" "}
            <span className="tabular-nums">{total}</span> {itemNoun}
            {total === 1 ? "" : "s"}
          </>
        )}
      </p>

      {pageCount > 1 && (
        <div className="flex items-center gap-1">
          <PagerButton
            aria-label="Previous page"
            disabled={page === 0}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft className="size-4" aria-hidden />
            Previous
          </PagerButton>

          {items.map((item, i) =>
            item === "ellipsis" ? (
              <span
                key={`gap-${i}`}
                aria-hidden
                className="grid size-9 place-items-center text-sm text-muted-ink"
              >
                …
              </span>
            ) : (
              <button
                key={item}
                type="button"
                aria-label={`Page ${item}`}
                aria-current={item === current ? "page" : undefined}
                onClick={() => onPageChange(item - 1)}
                className={cn(
                  "grid size-9 place-items-center rounded-full text-sm font-medium tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  item === current
                    ? "bg-soft text-ink"
                    : "text-ink hover:bg-soft",
                )}
              >
                {item}
              </button>
            ),
          )}

          <PagerButton
            aria-label="Next page"
            disabled={page >= pageCount - 1}
            onClick={() => onPageChange(page + 1)}
          >
            Next
            <ChevronRight className="size-4" aria-hidden />
          </PagerButton>
        </div>
      )}
    </nav>
  );
}

function PagerButton({
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        "flex h-9 items-center gap-1.5 rounded-full px-2.5 text-sm font-medium text-ink transition-colors hover:bg-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-40",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
