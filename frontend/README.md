# ODYSSEY TRANSFORM CORE — Dashboard

React 19 + TypeScript + Vite front end for **ODYSSEY TRANSFORM CORE**
(SIH26154, Team ODYSSEY NEXUS).

Setup, architecture, the full API reference and deployment instructions live in the
[project README](../README.md). This file covers the dashboard alone.

## Commands

```bash
npm install
npm run dev       # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run build     # type-check with tsc -b, then build to dist/
npm run lint      # oxlint
npm run preview   # serve the production build locally
```

Point the dev proxy at a different API with `ODYSSEY_API=http://host:port npm run dev`.

## How it talks to the backend

`src/api/client.ts` wraps every endpoint and sends the acting identity on each request:

```
X-Odyssey-User: analyst@odyssey.team
X-Odyssey-Role: analyst
```

Switching identity in the header re-boots the workspace, which is how the role switcher in
the shell demonstrates the analyst → approver → admin permission boundaries. Response types
live in `src/api/types.ts` and mirror the backend Pydantic schemas.

There is no router dependency: `App.tsx` owns the current view and keeps it in the query
string, so a view is linkable and the back button works.

## Layout

| Path | Role |
| --- | --- |
| `src/App.tsx` | Shell: navigation, identity switcher, view routing, toasts. |
| `src/views/OverviewView.tsx` | Pipeline counters, audit-chain health, recent runs. |
| `src/views/SourcesView.tsx` | Upload, paste or URL intake with a pre-commit security scan. |
| `src/views/TransformView.tsx` | Audience, tone, objective, detail, formats, user instruction. |
| `src/views/StudioView.tsx` | Artefact preview and edit, evidence, grounding, review, export. |
| `src/views/AuditView.tsx` | Chain status and the event ledger. |
| `src/components/ui.tsx` | Panels, badges, metrics, tabs, hashes, evidence callouts. |
| `src/state/workspace.ts` | External store: active document and transformation. |
| `src/lib/format.ts` | Dates, numbers, hashes, percentages. |
| `src/index.css`, `src/App.css` | Design tokens, layout and components. |

## Conventions

* One design-token palette in `index.css`; components use the tokens, not raw colours.
* API calls live in `src/api/client.ts`. Views never build URLs.
* Anything the user must not miss — a failed call, an approval reset — goes through
  `state/toast.ts` rather than an inline banner.
* Numbers in the UI are formatted through `lib/format.ts`, never `toFixed` at the call site.
