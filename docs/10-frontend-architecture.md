# 6. Frontend Architecture

## Stack

- Next.js 15 App Router
- React 19
- TypeScript
- TailwindCSS
- React Query
- Zustand
- Recharts
- Lucide icons

## Feature Slices

- `app`: route shell and global layout.
- `components/dashboard`: metric cards, charts, and transaction table.
- `components/assistant`: conversational AI surface.
- `components/uploads`: secure upload surface.
- `components/ui`: reusable primitives.
- `lib`: API and utility helpers.
- `store`: client state.

## Design System

The UI uses compact panels, 8px radius, semantic financial colors, dense dashboard layout, keyboard-friendly controls, and no marketing landing page. The first screen is the operational product experience.

The current product surface is a fraud-investigation workspace with:

- Operations overview metrics.
- Alert queue for suspicious transactions.
- Risk driver charting.
- Entity graph and evidence timeline panels.
- Case decision controls.
- Analyst session, investigation copilot, and evidence ingestion side rail.

## API Client Routing

All frontend API calls go through `src/lib/api.ts`. In development, the client falls back to:

```text
http://localhost:8000
```

In production, when `NEXT_PUBLIC_API_URL` is not set, the client uses same-origin requests:

```text
/api/...
```

This supports the AWS single-ALB deployment, where listener rules route `/api/*` to the backend
target group and all other paths to the frontend target group. Do not bake
`NEXT_PUBLIC_API_URL=http://localhost:8000` into production Docker images.

## Server and Client Rendering

The route layout, navigation, headings, and metadata remain Server Components. The `/cases` page
reads the short-lived `finsight_access_token` HttpOnly cookie and fetches the initial case
queue from `GET /api/cases` on the server. The fetch uses `cache: "no-store"` and the route is dynamic because the data is
user-specific, sensitive, and frequently changing. The access token cookie is issued and cleared
alongside the existing JSON token response; browser API calls continue to use the in-memory token.

The interactive queue, selection, filters, and context drawer remain in the Client Component. Its
TanStack Query observer uses the server result as initial data, then owns browser refetching. Zustand
owns only session/chat identifiers, TanStack Query owns fetched server state, and local React state
owns transient UI choices. On authenticated data failure the queue shows an unavailable state and
retry action; demo rows are shown only when there is no authenticated session.

The frontend task must set `API_INTERNAL_URL` to a backend origin reachable from the Next.js server.
Docker Compose sets it to `http://backend:8000`; production ECS must provide the corresponding
private backend origin. Server fetch errors are intentionally reduced to a generic message and are
not cached or rendered with backend details.

## Case Workflow State

Transactions remain immutable financial facts. A one-to-one investigation-case record stores status,
assignee, and a single decision; the migration creates case state for existing transactions, and both
direct transaction creation and CSV ingestion create it for new rows. Cases and notes are scoped to
the owning user. Assignment is currently self-assignment or unassignment because the backend has no
analyst directory or team-assignment contract.

`GET /api/cases` supplies the queue, `GET /api/cases/{id}` supplies its append-only notes, and
`PATCH /api/cases/{id}` handles assignment, status, or a decision. Decisions require a reason, set
their corresponding workflow status, and cannot be overwritten. Each mutation writes an audit event
in the same database transaction. `POST /api/cases/{id}/notes` appends a note and audit event.

TanStack Query owns the queue and selected-case detail. Mutations wait for server confirmation, then
update/invalidate affected case queries; no optimistic updates are used for audited actions. Upload
success invalidates the queue because CSV ingestion can create new cases. The UI does not display
risk scores or SLA values until those values are provided by real backend contracts.

## Tradeoffs

The first scaffold uses demo data where live backend data is not yet available. The API client and
session store are present so live auth and tool calls can be connected without reshaping the
component tree. Demo data remains an explicit unauthenticated mode rather than a fallback for failed
live requests.
