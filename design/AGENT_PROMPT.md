# Agent prompt — implement the Accordance frontend

Paste everything below this line into a fresh agent session inside `D:\WhyStill\gri-lens`.

---

You are implementing the new frontend for **Accordance**, a local-first app that
analyzes ESG/sustainability report PDFs against GRI disclosures. The FastAPI
backend is complete and is the source of truth — build ONLY what it serves.

## Assets you must read first

- `design/README.md` — manifest: every screen id → name → backing endpoint
- `design/png/*.png` — visual reference for all 24 screens (@2x)
- `design/screens-tailwind.html` — self-contained Tailwind render of every
  frame; use it for exact spacing, typography, colors, border radii
- `PRODUCT.md` — product spec, domain model, UX conventions
- `backend/src/accordance/api/*.py` + `models.py` — the real API contract

## Stack

React 19 + TypeScript + Vite 8 + Tailwind 4 + react-router-dom 7 + react-pdf 10.
Dependencies are already in `frontend/` — explore `frontend/src` first; this is
a visual rewrite, the backend must not change. The design mimics HeroUI v3
components (soft chips, tertiary buttons, app sidebar); HeroUI is NOT
installed — implement the look with Tailwind using the exported HTML/tokens
(`$accent`, `$surface`, `$success|warning|danger`, Inter) or add the library
only if trivially compatible. Cookies handle auth — same-origin fetch with
`credentials: 'include'`, no token plumbing.

## Backend contract (verified — do not guess)

Auth: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` →
`{username, is_admin}` only. Cookie session; 401 → redirect to login.
Ownership: non-admin users get 404 for other users' reports — show 404 screen.

Reports: `GET /api/reports?q=&limit=&offset=` → `ReportSummary{id, name,
created_at, version_count, latest}` where `latest` = RunSummary with `status`
(queued|extracting|indexing|judging|completed|failed|cancelled), `counts`
{covered, partial, missing, error}, `error`. **No cost or score field — do not
display report spend or average grades.** `GET/PATCH(rename)/DELETE
/api/reports/{id}`; `POST /api/reports/{id}/versions` (new version upload);
`GET /api/reports/{id}/compare` → `summary_delta{covered,partial,missing,
error}` (each `{a,b,delta}`) + `diff[]` of `DiffEntry{disclosure_id, standard,
a:FindingView|null, b:FindingView|null, change}` — per-row scores come from
a/b FindingViews.

Runs: `POST /api/runs` = multipart pdf + `disclosure_ids[]`; `GET/DELETE
/api/runs/{id}`; `GET /api/runs/{id}/pdf`; `GET /api/runs/{id}/stream` =
SSE; `POST stop|retry|judge-more|fork`. RunSummary: pdf_filename, uploaded_at,
completed_at, status, error, counts, selected_total, cost_usd.
FindingView: disclosure_id, title, score (0-5), status
(covered|partial|missing|error), elements[], evidence_page, evidence_excerpt,
note, fix, na_reason, has_vision. "N/A" findings = score 0 + na_reason.
NO chunk/retrieval metadata in findings — that lives only in traces.

Corrections: `POST /api/runs/{id}/corrections` {disclosure_id, corrected_score,
corrected_elements, rationale}; `GET` returns ONLY live (non-superseded)
corrections → CorrectionView adds agent_score, reviewer, created_at. `DELETE
/api/runs/{id}/corrections/{cid}`. No history endpoint — the drawer shows the
live list only.

Traces: `GET /api/runs/{id}/traces` — retrieval queries, chunks, prompt
attempts per disclosure.

KB: `GET /api/kb` grouped disclosures; `GET /api/kb/presets`.
Export: `GET /api/runs/{id}/export/coverage` + report-level exports.
Self: `GET /api/me/stats` → `{pdf_count, cost_usd}` only.

Admin (is_admin only): `GET /api/admin/users` →
`AdminUserView{id,username,is_admin,is_active,created_at,pdf_count,cost_usd}`
— **no email, no last_active in the list**. `GET /api/admin/users/{id}` adds
last_active, cost_by_kind, recent_runs (AdminUserRun: pdf_filename, status,
cost_usd, timestamps — no report names), daily_usage. `POST
/api/admin/users` = `{username, password}` ONLY (no email, no is_admin — admin
flag is a separate `PATCH`); `PATCH` = `{is_admin?, is_active?}`; `POST
reset-password` = `{password}` — admin TYPES it, min 8 chars.

## Screens to build (route → design file)

1. `/login` — HNvYH
2. `/` dashboard — hfAK6 (reports table: report | latest status chip |
   findings covered/partial/missing counts | versions | updated | kebab;
   search + pagination from `q/limit/offset`; upload dropzone) + hmq2r empty
3. scope modal — dDp4P (presets + grouped disclosure checkboxes → POST /runs)
4. `/reports/:id` — R1CHA4 (stat cards: latest status, coverage, versions,
   last updated; versions table: ver|kind|pdf|status|findings|run; dropzone →
   POST versions; rename inline → PATCH; delete → g4y9H modal)
5. `/runs/:id/live` — YcNKI (stepper extract→index→judge, SSE feed, cancel,
   live cost) + ZPQRU failed state (error alert + Retry)
6. `/runs/:id` findings — oCrsz (table + Covered/Partial/Missing/N·A/
   Errors/Overridden filter chips; expanded row shows note/fix/evidence
   p.N/excerpt; "Open evidence" → 7; correction modal tHTmC → POST;
   corrections drawer zuuPx → GET live list; trace drawer GskRE → GET traces)
7. evidence dock — M2P6bQ (react-pdf viewer on evidence_page + excerpt card —
   NO highlight box, API has no coordinates)
8. `/reports/:id/compare` — HWw7B (vA/vB pickers; delta cards:
   Covered/Partial/Missing counts + Changed findings; diff table with
   Improved/Regressed/Added/Removed/Unchanged chips mapped from `change`)
9. export modal — ePZwA → coverage export download
10. `/admin/users` — C0do7g (user|role chip|status chip|runs|spend|joined —
    NO email/last-active; kebab actions) + zQ9YS create modal
    (username+password only) + PATCH admin/active
11. `/admin/users/:id` — M6GrR (stats: runs|spend|last active|member since;
    spend-by-kind bars; daily usage bars; recent runs table pdf|status|cost|
    date) + FqvCG reset modal (admin types password, min 8)
12. `/profile` — Sc1ti (username + admin chip; My runs|Reports|Total spend
    stats; My reports table — no email, no password form)
13. toasts — PSZPZ (success + error patterns for every mutation)
14. 404 — o5FLkC

App shell: sidebar `y2aKp` — brand "Lens / GRI disclosure analysis", nav
(Analyses; Users admin-only), user card bottom (avatar initials, username,
analyses·spend, logout). 1440×900 desktop layout, tables fill available
height, footer pinned bottom.

## Hard rules

- Every field on screen must trace to a response model — if the API doesn't
  return it, it doesn't render. Do not invent aggregates.
- After each screen: run `npm run dev` (proxy /api → localhost:8000), verify
  against the real backend, screenshot-compare with `design/png/<id>.png`.
- `npx tsc --noEmit`, `npx eslint`, `npx vitest run` must pass.
- Small components, typed API client with one module per resource, typed
  models mirroring the Pydantic shapes, React Query or equivalent for
  fetching/SSE state.
- No comments unless necessary; match existing repo conventions.
