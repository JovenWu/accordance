import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, ListChecks, Loader2, Play, X } from "lucide-react";

import { getKb, getPresets, uploadPdf } from "@/api";
import { ScopeModal } from "@/components/ScopeModal";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { KbStandard, Preset } from "@/types";

export function NewAnalysisCard() {
  const [file, setFile] = useState<File | null>(null);
  const [groups, setGroups] = useState<KbStandard[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  const nav = useNavigate();

  useEffect(() => {
    getKb()
      .then((g) => {
        setGroups(g);
        setSelected(
          new Set(
            g
              .flatMap((grp) => grp.disclosures)
              .filter((d) => d.status === "current")
              .map((d) => d.id),
          ),
        );
      })
      .catch(() => setError("Could not load the disclosure catalog."));
    getPresets().then(setPresets).catch(() => {});
  }, []);

  function pickFile(f: File) {
    if (f.type !== "application/pdf" && !f.name.endsWith(".pdf")) {
      setError("Please upload a PDF file.");
      return;
    }
    setError(null);
    setFile(f);
  }

  async function start() {
    if (!file || !selected || selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadPdf(file, [...selected]);
      toast({
        title: result.deduplicated ? "Already analyzed" : "Analysis started",
        message: result.deduplicated
          ? "This PDF matches an existing run — showing it instead."
          : file.name,
      });
      nav(`/runs/${result.run_id}/live`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast({ title: "Upload failed", message: msg, variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  const allCount = groups.reduce((n, g) => n + g.disclosures.length, 0);
  const selCount = selected?.size ?? 0;
  const scopeLabel =
    selected === null
      ? "Loading scope…"
      : selCount === allCount
        ? `All GRI disclosures · ${allCount}`
        : `${selCount} of ${allCount} disclosures`;

  return (
    <section className="flex w-full flex-col gap-4 rounded-3xl bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-[15px] font-semibold text-ink">New analysis</h2>
        <span className="text-xs text-muted-ink">
          PDF up to 100 MB · results stay on this machine
        </span>
      </div>

      {file ? (
        <div className="flex h-[132px] items-center justify-between rounded-2xl border border-line-strong bg-soft-2 px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-deep">
              <FileUp className="size-5" aria-hidden />
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate text-sm font-medium text-ink">
                {file.name}
              </span>
              <span className="text-xs text-muted-ink">
                {(file.size / 1024 / 1024).toFixed(1)} MB · ready to analyze
              </span>
            </div>
          </div>
          <button
            type="button"
            aria-label="Remove file"
            onClick={() => setFile(null)}
            disabled={busy}
            className="grid size-6 shrink-0 place-items-center rounded-xl bg-soft text-ink transition-colors hover:bg-soft-2"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      ) : (
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload a sustainability report PDF"
          className={cn(
            "flex h-[132px] flex-col items-center justify-center gap-2 rounded-2xl border bg-soft-2 text-center transition-colors",
            dragging
              ? "border-accent-deep bg-accent-soft/40"
              : "border-line-strong hover:border-muted-ink/40",
          )}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files[0];
            if (f) pickFile(f);
          }}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) pickFile(f);
              e.target.value = "";
            }}
          />
          <span className="grid size-10 place-items-center rounded-full bg-accent-soft text-accent-deep">
            <FileUp className="size-5" aria-hidden />
          </span>
          <p className="text-sm font-medium text-ink">
            Drop a sustainability report PDF here, or browse files
          </p>
          <p className="text-xs text-muted-ink">
            We extract the text, index it, then judge every selected disclosure
          </p>
        </div>
      )}

      {error && (
        <p role="alert" className="text-[13px] text-danger">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
        <span className="text-[13px] font-medium text-muted-ink">Scope</span>
        <Chip tone="accent" className="px-1 py-0.5 text-[11px]">
          {scopeLabel}
        </Chip>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setScopeOpen(true)}
          disabled={selected === null}
        >
          <ListChecks aria-hidden />
          Choose scope
        </Button>
        <Button
          className="ml-auto"
          onClick={start}
          disabled={busy || !file || !selected || selected.size === 0}
        >
          {busy ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <Play aria-hidden />
          )}
          {busy ? "Starting…" : "Start analysis"}
        </Button>
      </div>

      <ScopeModal
        open={scopeOpen}
        onClose={() => setScopeOpen(false)}
        groups={groups}
        presets={presets}
        selected={selected ?? new Set()}
        onApply={setSelected}
      />
    </section>
  );
}
