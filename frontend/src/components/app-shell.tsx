import Link from "next/link";
import type { Route } from "next";
import { DashboardWorkspace } from "@/components/dashboard/dashboard-workspace";
import {
  Bell,
  BriefcaseBusiness,
  Database,
  FileSearch,
  Gauge,
  Network,
  Search,
  Settings,
  ShieldAlert,
  Siren
} from "lucide-react";

type WorkspaceRoute = "triage" | "cases" | "graph" | "evidence" | "data";

const navigation: Array<{ id: WorkspaceRoute; label: string; href: `/${string}`; icon: typeof Gauge }> = [
  { id: "triage", label: "Triage", href: "/", icon: Gauge },
  { id: "cases", label: "Cases", href: "/cases", icon: BriefcaseBusiness },
  { id: "graph", label: "Graph", href: "/graph", icon: Network },
  { id: "evidence", label: "Evidence", href: "/evidence", icon: FileSearch },
  { id: "data", label: "Data", href: "/data", icon: Database }
];

const routeCopy: Record<WorkspaceRoute, { eyebrow: string; title: string; description: string }> = {
  triage: {
    eyebrow: "Fraud command center",
    title: "Triage live-risk alerts and document decisions",
    description: "Select an alert, inspect supporting evidence, and commit an auditable disposition."
  },
  cases: {
    eyebrow: "Case operations",
    title: "Review assigned cases and escalation state",
    description: "Track ownership, SLA pressure, and disposition readiness for active investigations."
  },
  graph: {
    eyebrow: "Entity intelligence",
    title: "Trace connected accounts, devices, and beneficiaries",
    description: "Use shared signals to understand how an alert relates to broader entity behavior."
  },
  evidence: {
    eyebrow: "Evidence review",
    title: "Validate signals before analyst disposition",
    description: "Inspect uploaded evidence, extracted context, and reviewer-ready signal summaries."
  },
  data: {
    eyebrow: "Data controls",
    title: "Monitor ingestion quality and investigation data",
    description: "Keep transaction, document, and model-grounding inputs visible to operations teams."
  }
};

export function AppShell({ activeRoute }: { activeRoute: WorkspaceRoute }) {
  const copy = routeCopy[activeRoute];

  return (
    <main className="min-h-screen bg-background text-foreground">
      <a
        className="sr-only rounded-md bg-panel px-3 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50"
        href="#dashboard"
      >
        Skip to dashboard
      </a>

      <div className="grid min-h-screen lg:grid-cols-[244px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-panel lg:flex lg:flex-col" aria-label="Sidebar navigation">
          <div className="flex h-16 items-center gap-3 border-b border-border px-5">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-danger/10 text-danger">
              <ShieldAlert aria-hidden className="h-5 w-5" />
            </span>
            <div>
              <p className="text-sm font-bold">FinSight AI</p>
              <p className="text-xs text-muted">Fraud operations</p>
            </div>
          </div>
          <nav className="flex-1 space-y-1 px-3 py-4 text-sm font-medium" aria-label="Workspace">
            {navigation.map((item) => {
              const isActive = item.id === activeRoute;
              return (
                <Link
                  key={item.label}
                  className={`flex h-9 items-center gap-3 rounded-md px-3 transition ${
                    isActive
                      ? "bg-accent/10 text-accent"
                      : "text-muted hover:bg-background hover:text-foreground"
                  }`}
                  href={item.href as Route}
                  aria-current={isActive ? "page" : undefined}
                >
                  <item.icon aria-hidden className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-border p-3">
            <Link className="flex h-9 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition hover:bg-background hover:text-foreground" href={"/data" as Route}>
              <Settings aria-hidden className="h-4 w-4" />
              Controls
            </Link>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-20 border-b border-border bg-panel/95 backdrop-blur">
            <nav
              className="flex gap-2 overflow-x-auto border-b border-border px-4 py-2 text-sm font-medium [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:hidden"
              aria-label="Mobile navigation"
            >
              {navigation.map((item) => {
                const isActive = item.id === activeRoute;
                return (
                  <Link
                    key={item.label}
                    className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-md border px-3 transition ${
                      isActive
                        ? "border-accent/30 bg-accent/10 text-accent"
                        : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
                    }`}
                    href={item.href as Route}
                    aria-current={isActive ? "page" : undefined}
                  >
                    <item.icon aria-hidden className="h-4 w-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
            <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:px-6 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-danger">
                  <Siren aria-hidden className="h-4 w-4" />
                  {copy.eyebrow}
                </p>
                <h1 className="text-xl font-semibold leading-tight sm:text-2xl">{copy.title}</h1>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <label className="relative block min-w-0 sm:w-[340px]" htmlFor="workspace-search">
                  <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <span className="sr-only">Search cases, entities, merchants, or transaction ids</span>
                  <input
                    id="workspace-search"
                    type="search"
                    className="h-10 w-full rounded-md border border-border bg-white pl-9 pr-3 text-sm outline-none transition placeholder:text-muted/70 hover:border-accent/70 focus:border-accent focus:ring-2 focus:ring-accent/20"
                    placeholder="Search cases, entities, merchants..."
                  />
                </label>
                <button className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 text-sm font-semibold text-danger transition hover:border-danger/50">
                  <Bell aria-hidden className="h-4 w-4" />
                  12 open alerts
                </button>
              </div>
            </div>
          </header>

          <div className="px-4 py-4 sm:px-6">
            <section id="dashboard" className="min-w-0 space-y-4" aria-labelledby="dashboard-heading">
              <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="max-w-3xl">
                  <h2 id="dashboard-heading" className="text-base font-semibold">Investigation workspace</h2>
                  <p className="mt-1 text-sm text-muted">{copy.description}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {["Unassigned", "High risk", "SLA breach"].map((filter, index) => (
                    <span
                      key={filter}
                      className={`inline-flex h-8 items-center rounded-md border px-3 text-xs font-semibold ${
                        index === 1
                          ? "border-danger/40 bg-danger/10 text-danger"
                          : "border-border bg-white text-muted"
                      }`}
                    >
                      {filter}
                    </span>
                  ))}
                </div>
              </div>
              <DashboardWorkspace />
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
