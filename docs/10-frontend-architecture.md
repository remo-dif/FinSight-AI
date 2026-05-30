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

## Tradeoffs

The first scaffold uses demo data where authentication is not yet wired in the browser. The API client and session store are present so live auth and tool calls can be connected without reshaping the component tree.
