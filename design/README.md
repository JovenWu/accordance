# Design export — Accordance

Exported from `D:/WhyStill/gri.pen` (Pencil). `png/` holds one 2x PNG per frame;
`screens-tailwind.html` is a single self-contained Tailwind HTML file with every
frame (layer names/ids preserved as data attributes).

| File id | Screen | Backed by |
|---|---|---|
| HNvYH | Login | POST /api/auth/login |
| hfAK6 | Dashboard (reports table) | GET /api/reports (q, limit, offset) |
| hmq2r | Dashboard — empty state | GET /api/reports = [] |
| dDp4P | Modal — Analysis scope | GET /api/kb, GET /api/kb/presets |
| R1CHA4 | Report detail (versions) | GET /api/reports/{id}, PATCH rename, DELETE |
| YcNKI | Run in progress (SSE feed) | GET /api/runs/{id}/stream, POST stop |
| oCrsz | Run findings | GET /api/runs/{id} findings |
| M2P6bQ | Evidence dock (PDF page) | GET /api/runs/{id}/pdf |
| tHTmC | Modal — Correction | POST /api/runs/{id}/corrections |
| GskRE | Drawer — Judge trace | GET /api/runs/{id}/traces |
| HWw7B | Compare versions | GET /api/reports/{id}/compare |
| ePZwA | Modal — Export coverage | GET /api/runs/{id}/export/coverage |
| C0do7g | Admin — users list | GET /api/admin/users |
| M6GrR | Admin — user detail | GET /api/admin/users/{id} |
| ZPQRU | Run failed state | GET /api/runs/{id} status=failed |
| g4y9H | Modal — Delete report | DELETE /api/reports/{id} |
| o5FLkC | 404 | access control 404s |
| W9Ifhx | Modal — Rename report | PATCH /api/reports/{id} |
| zQ9YS | Modal — Create user | POST /api/admin/users {username,password} |
| FqvCG | Modal — Reset password | POST /api/admin/users/{id}/reset-password {password} |
| Sc1ti | Profile | GET /api/auth/me, GET /api/me/stats |
| PSZPZ | Toasts (success + error) | — |
| zuuPx | Drawer — Corrections (live) | GET /api/runs/{id}/corrections |
| o37PZp | HeroUI component sheet | design system reference |

Notes for the implementing agent:

- All content is intentionally limited to what the backend exposes — do not
  re-add report spend, score averages, emails, or correction history.
- Stack: React 19 + TypeScript + Vite + Tailwind 4 + react-pdf + react-router 7.
- Components are styled after HeroUI v3 — map chips/buttons/inputs/modals/tables
  to the real library rather than hand-styling.
- `screens-tailwind.html` is a rendering reference, not production markup —
  component boundaries in the React app follow the backend payloads, not the
  flattened DOM.
