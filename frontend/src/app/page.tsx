import { AlertTriangle, ArrowDownUp, CalendarClock, WalletCards } from "lucide-react";
import { ChatPanel } from "@/components/assistant/chat-panel";
import { MetricCard } from "@/components/dashboard/metric-card";
import { SpendingChart } from "@/components/dashboard/spending-chart";
import { TransactionsTable } from "@/components/dashboard/transactions-table";
import { UploadPanel } from "@/components/uploads/upload-panel";

export default function Home() {
  return (
    <main className="min-h-screen bg-background">
      <a
        className="sr-only rounded-md bg-panel px-3 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50"
        href="#dashboard"
      >
        Skip to dashboard
      </a>
      <header className="border-b border-border bg-panel">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">Finance workspace</p>
            <h1 className="mt-1 text-2xl font-bold leading-tight sm:text-3xl">Personal Finance AI Assistant</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
              Multimodal analytics, budgeting, anomaly detection, and reviewed AI answers.
            </p>
          </div>
          <nav className="flex flex-wrap gap-1 text-sm font-medium text-muted" aria-label="Primary">
            <a className="rounded-md px-3 py-2 transition hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" href="#dashboard">Dashboard</a>
            <a className="rounded-md px-3 py-2 transition hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" href="#assistant">Assistant</a>
            <a className="rounded-md px-3 py-2 transition hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" href="#uploads">Uploads</a>
          </nav>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-5 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_420px] lg:px-8">
        <section id="dashboard" className="space-y-5" aria-labelledby="dashboard-heading">
          <div>
            <h2 id="dashboard-heading" className="text-lg font-semibold">Dashboard</h2>
            <p className="mt-1 text-sm text-muted">A quick read on cash flow, spend patterns, and items needing review.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Net Cash Flow" value="$2,495" detail="+8.3% vs last month" icon={ArrowDownUp} tone="success" />
            <MetricCard label="Spending" value="$1,705" detail="72% of target" icon={WalletCards} tone="accent" />
            <MetricCard label="Anomalies" value="2" detail="Needs review" icon={AlertTriangle} tone="danger" />
            <MetricCard label="Recurring" value="7" detail="$312 monthly" icon={CalendarClock} tone="warning" />
          </div>
          <div className="grid items-start gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
            <SpendingChart />
            <TransactionsTable />
          </div>
        </section>

        <aside className="space-y-4 lg:pt-[76px]" aria-label="Assistant and uploads">
          <section id="assistant" aria-labelledby="assistant-heading">
            <ChatPanel />
          </section>
          <section id="uploads" aria-labelledby="uploads-heading">
            <UploadPanel />
          </section>
        </aside>
      </div>
    </main>
  );
}
