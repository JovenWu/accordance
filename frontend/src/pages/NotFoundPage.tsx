import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

/**
 * Shown for an unknown URL and for any resource the API reports as 404
 * (including reports another user owns — the API returns 404 for those).
 */
export function NotFoundPage({
  title = "Page not found",
  message = "The report, run or view you were looking for doesn't exist or was removed.",
}: {
  title?: string;
  message?: string;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-4 sm:p-6 lg:p-10">
      <span className="text-[72px] font-bold leading-none text-accent">
        404
      </span>
      <h1 className="text-[20px] font-semibold text-ink">{title}</h1>
      <p className="max-w-md text-center text-[13px] text-muted-ink">
        {message}
      </p>
      <div className="h-2" />
      <Link
        to="/"
        className="inline-flex h-9 items-center gap-2 rounded-full bg-accent px-4 text-sm font-medium text-accent-ink transition-colors hover:bg-accent/90"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to Analyses
      </Link>
    </div>
  );
}
