import { ChatPanel } from "@/components/assistant/chat-panel";
import { AuthPanel } from "@/components/auth/auth-panel";
import { DashboardWorkspace } from "@/components/dashboard/dashboard-workspace";
import { UploadPanel } from "@/components/uploads/upload-panel";
import {
  Bell,
  BriefcaseBusiness,
  Database,
  FileSearch,
  Gauge,
  Network,
  Search,
  Settings,
  ShieldAlert
} from "lucide-react";

const navigation = [
  { label: "Triage", icon: Gauge, active: true },
  { label: "Cases", icon: BriefcaseBusiness },
  { label: "Graph", icon: Network },
  { label: "Evidence", icon: FileSearch },
  { label: "Data", icon: Database }
];

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <a
        className="sr-only rounded-md bg-panel px-3 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50"
        href="#dashboard"
      >
        Skip to dashboard
      </a>

      <div className="grid min-h-screen lg:grid-cols-[244px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-panel lg:flex lg:flex-col" aria-label="Primary navigation">
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
            {navigation.map((item) => (
              <a
                key={item.label}
                className={`flex h-9 items-center gap-3 rounded-md px-3 transition ${
                  item.active
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:bg-background hover:text-foreground"
                }`}
                href="#dashboard"
                aria-current={item.active ? "page" : undefined}
              >
                <item.icon aria-hidden className="h-4 w-4" />
                {item.label}
              </a>
            ))}
          </nav>
          <div className="border-t border-border p-3">
            <a className="flex h-9 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition hover:bg-background hover:text-foreground" href="#settings">
              <Settings aria-hidden className="h-4 w-4" />
              Controls
            </a>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-20 border-b border-border bg-panel/95 backdrop-blur">
            <nav
              className="flex gap-2 overflow-x-auto border-b border-border px-4 py-2 text-sm font-medium lg:hidden"
              aria-label="Primary navigation"
            >
              {navigation.map((item) => (
                <a
                  key={item.label}
                  className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-md border px-3 transition ${
                    item.active
                      ? "border-accent/30 bg-accent/10 text-accent"
                      : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
                  }`}
                  href="#dashboard"
                  aria-current={item.active ? "page" : undefined}
                >
                  <item.icon aria-hidden className="h-4 w-4" />
                  {item.label}
                </a>
              ))}
            </nav>
            <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:px-6 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">Alert triage queue</p>
                <h1 className="text-xl font-semibold leading-tight">Investigate suspicious transaction activity</h1>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <label className="relative block min-w-0 sm:w-[340px]">
                  <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <span className="sr-only">Search cases, entities, merchants, or transaction ids</span>
                  <input
                    className="h-10 w-full rounded-md border border-border bg-white pl-9 pr-3 text-sm outline-none transition placeholder:text-muted/70 hover:border-accent/70 focus:border-accent focus:ring-2 focus:ring-accent/20"
                    placeholder="Search cases, entities, merchants..."
                  />
                </label>
                <button className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted transition hover:border-accent/60 hover:text-foreground">
                  <Bell aria-hidden className="h-4 w-4" />
                  12 alerts
                </button>
              </div>
            </div>
          </header>

          <div className="grid gap-4 px-4 py-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_380px]">
            <section id="dashboard" className="min-w-0 space-y-4" aria-labelledby="dashboard-heading">
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-panel p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 id="dashboard-heading" className="text-base font-semibold">Operations overview</h2>
                  <p className="mt-1 text-sm text-muted">Prioritize alerts, review evidence, and move cases toward a decision.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {["Unassigned", "High risk", "SLA breach"].map((filter, index) => (
                    <button
                      key={filter}
                      className={`h-8 rounded-md border px-3 text-xs font-semibold transition ${
                        index === 1
                          ? "border-danger/40 bg-danger/10 text-danger"
                          : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
                      }`}
                      aria-pressed={index === 1}
                    >
                      {filter}
                    </button>
                  ))}
                </div>
              </div>
              <DashboardWorkspace />
            </section>

            <aside className="space-y-4" aria-label="Investigation side rail">
              <AuthPanel />
              <section id="assistant" aria-labelledby="assistant-heading">
                <ChatPanel />
              </section>
              <section id="uploads" aria-labelledby="uploads-heading">
                <UploadPanel />
              </section>
            </aside>
          </div>
        </div>
      </div>
    </main>
  );
}
