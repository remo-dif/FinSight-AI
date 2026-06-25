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

## Tradeoffs

The first scaffold uses demo data where live backend data is not yet available. The API client and
session store are present so live auth and tool calls can be connected without reshaping the
component tree.
