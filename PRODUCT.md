# Product

Name: **Accordance**

A local-first tool for ESG analysts that grades sustainability-report PDFs
against the GRI Standards using an LLM judge, then lets humans review,
correct, compare and export the results.

- Audience: ESG analysts at a firm (dense, data-first workflows)
- Design file: `D:\WhyStill\gri.pen` (Pencil)
- Design system: existing HeroUI kit already in the file — light theme,
  Inter, accent `#0485F7`, `$accent/* $surface/* $foreground/* $field/*
  $separator/* $success/* $warning/* $danger/*` tokens

## Core loop

Upload PDF → extract → index (chunks + embeddings + FTS in Postgres) →
LLM judges each selected disclosure (hybrid retrieval, rerank, vision
fallback, re-judge on missing) → findings stream live over SSE → human
review/corrections → export coverage matrix / compare versions.

## Domain model (backend-verified)

- **Report** — named project; renameable, soft-deletable, owner-scoped
  (admins see all)
- **Run / Version** — every execution is versioned; `kind` = initial /
  retry / fork / update (new PDF); dedup by PDF hash
- **Finding** — per-disclosure verdict: score 0–5 (0 = N/A, 1 = missing …
  5 = complete), per-element verdicts (found/partial/missing + page),
  evidence excerpt + page, suggested fix, vision-fallback flag
- **Correction** — human override (score + elements + rationale,
  supersede history)
- **Judge trace** — retrieval queries, chunk ids, pages, latency, model,
  parse path, evidence verification
- **Export** — XLSX coverage matrix (one run, all versions of a report,
  or cherry-picked runs)
- **Compare** — diff any two versions; per-disclosure change
  classification (improved/regressed/added/removed/unchanged)
- **Admin** — user CRUD, active/admin toggles, password resets, per-user
  usage (PDFs, cost by run kind, recent runs, daily usage)
- **KB** — ~470 GRI disclosures grouped by standard + 4 sector presets
  (Oil & Gas, Coal, Agriculture, Mining)

## Screens in `gri.pen`

| Screen | Covers |
|---|---|
| Login | `POST /api/auth/login` |
| Dashboard / Analyses | upload dropzone, scope summary, reports table (search, pagination, status chips, covered/partial/missing counts, versions, updated, kebab actions) |
| Modal — Analysis Scope | sector presets + grouped disclosure picker + selected count → `POST /api/runs` |
| Report Detail | rename/delete/compare, stats (latest status, coverage, versions, last updated), versions table (kind/status/findings/uploaded), upload new version |
| Run In Progress | pipeline stepper (Extract→Index→Judge→Finalize), progress bar, live findings feed (SSE) |
| Run Findings | distribution summary, filter chips (Covered/Partial/Missing/N·A/Errors/Overridden), findings table, expanded finding (elements checklist, evidence excerpt + page, assessment, suggested fix) |
| Evidence Dock | PDF page viewer at `evidence_page`, finding context + excerpt, elements, Correct/Trace actions |
| Modal — Correction | score 0–5 pill selector, per-element overrides, rationale |
| Drawer — Judge Trace | retrieval queries, chunks, prompt, attempt history (initial + vision fallback) |
| Compare Versions | A/B pickers, delta summary (covered/partial/missing, changed findings), diff table with change chips |
| Modal — Export Coverage | run checklist, options, download XLSX |
| Admin Users | users table (role, status, runs, spend, joined), create user |
| Admin User Detail | stats (runs, spend, last active, member since), spend by run kind, daily usage bars, recent runs, reset/revoke/disable actions |
| Dashboard Empty | first-run empty state |
| Modal — Delete Report | irreversible delete confirmation |
| Run Failed | failed step highlighted, error alert, retry, partial findings preserved |
| 404 | centered not-found with back action |
| Modal — Rename Report | inline rename over report detail |
| Modal — Create User | username + temporary password (min 8) |
| Modal — Reset Password | admin sets new password (min 8) |
| Screen — Profile | `/api/me` + `/api/me/stats` — account, own runs/reports/spend, own reports table |
| Screen — Toasts | success/error notification stack |
| Drawer — Corrections | live overrides for the run — corrected score, rationale, reviewer, timestamp (superseded rows are not exposed by the API) |


## UX conventions

- Evidence-first finding rows: score → status → disclosure → page ref
- Corrections surface as "Overridden" chips in the findings table
- Live progress is the in-progress state of the run screen, not a
  separate flow
- Version selection via checkboxes in the report versions table
- Dense but readable tables; muted metadata, chips for all statuses
