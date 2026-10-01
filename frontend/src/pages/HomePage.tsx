import { useEffect, useRef, useState } from "react";
import { Download, Plus } from "lucide-react";

import { ExportDialog } from "@/components/ExportDialog";
import { NewAnalysisCard } from "@/components/NewAnalysisCard";
import { ReportsTable } from "@/components/ReportsTable";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/input";

export function HomePage() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [exportOpen, setExportOpen] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 sm:px-6 lg:px-8 lg:pt-5">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-[22px] font-semibold text-ink">Analyses</h1>
          <p className="text-[13px] text-muted-ink">
            Sustainability reports graded against the GRI Standards
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2.5 sm:w-auto">
          <SearchInput
            className="w-full sm:w-60"
            inputProps={{
              placeholder: "Search reports…",
              value: query,
              onChange: (e) => setQuery(e.target.value),
              "aria-label": "Search reports",
            }}
          />
          <Button variant="outline" onClick={() => setExportOpen(true)}>
            <Download aria-hidden />
            Export
          </Button>
          <Button
            onClick={() =>
              cardRef.current?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              })
            }
          >
            <Plus aria-hidden />
            New analysis
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pb-6 pt-3 sm:px-6 lg:px-8 lg:pb-8">
        <div ref={cardRef} className="scroll-mt-4">
          <NewAnalysisCard />
        </div>
        <ReportsTable query={debounced} />
      </div>

      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} />
    </div>
  );
}
