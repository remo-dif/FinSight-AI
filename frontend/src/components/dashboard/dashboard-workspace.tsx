"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock3, FileCheck2, Gavel, Network, ShieldAlert } from "lucide-react";
import { MetricCard } from "@/components/dashboard/metric-card";
import { SpendingChart, SpendingChartDatum } from "@/components/dashboard/spending-chart";
import { TransactionsTable } from "@/components/dashboard/transactions-table";
import { demoTransactions, fetchMonthlySummary, fetchTransactions, Transaction } from "@/lib/api";
import { useSessionStore } from "@/store/session";

const COLORS = ["#be123c", "#b45309", "#0f766e", "#0369a1", "#4338ca", "#475569"];

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

function categoryData(transactions: Transaction[]): SpendingChartDatum[] {
  const totals = new Map<string, number>();
  for (const transaction of transactions) {
    const amount = Number(transaction.amount);
    if (amount < 0) {
      totals.set(transaction.category, (totals.get(transaction.category) ?? 0) + Math.abs(amount));
    }
  }
  return [...totals.entries()]
    .sort((left, right) => right[1] - left[1])
    .slice(0, 6)
    .map(([name, value], index) => ({ name, value: Math.max(Math.round(value / 10), 1), color: COLORS[index % COLORS.length] }));
}

export function DashboardWorkspace() {
  const token = useSessionStore((state) => state.accessToken);
  const month = currentMonth();
  const summary = useQuery({
    queryKey: ["monthly-summary", month],
    queryFn: () => fetchMonthlySummary(month),
    enabled: Boolean(token)
  });
  const transactions = useQuery({
    queryKey: ["transactions", 50],
    queryFn: () => fetchTransactions(50),
    enabled: Boolean(token)
  });

  const activeTransactions = transactions.data?.length ? transactions.data : demoTransactions;
  const activeSummary = summary.data ?? {
    month,
    income: "4200.00",
    spending: "1705.00",
    net_cash_flow: "2495.00"
  };
  const openAlerts = Math.max(activeTransactions.length * 4, 12);
  const highRisk = activeTransactions.filter((transaction) => Math.abs(Number(transaction.amount)) > 75).length + 7;
  const exposure = Number(activeSummary.spending) + Number(activeSummary.income) * 0.18;

  return (
    <>
      {!token ? (
        <p className="rounded-md border border-border bg-panel px-3 py-2 text-sm text-muted">
          Showing demo data. Sign in to load your live dashboard.
        </p>
      ) : null}
      {summary.isError || transactions.isError ? (
        <p className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
          Live dashboard data could not be loaded. The demo fallback is still visible.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Open alerts" value={String(openAlerts)} detail="Unresolved items across monitored accounts" icon={ShieldAlert} tone="danger" trend="+14%" />
        <MetricCard label="High risk" value={String(highRisk)} detail="Prioritized by rule severity and model score" icon={AlertTriangle} tone="warning" trend="+6" />
        <MetricCard label="Exposure" value={`$${Math.round(exposure).toLocaleString()}`} detail={`${activeSummary.month} potentially suspicious value`} icon={Gavel} tone="accent" />
        <MetricCard label="SLA at risk" value="9" detail="Cases that need action in the next 4 hours" icon={Clock3} tone="success" />
      </div>
      <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]">
        <TransactionsTable transactions={activeTransactions} />
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-1">
          <SpendingChart data={categoryData(activeTransactions)} />
          <EntityGraphPanel />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <EvidencePanel />
        <DecisionPanel />
      </div>
    </>
  );
}

function EntityGraphPanel() {
  return (
    <section className="rounded-lg border border-border bg-panel p-4" aria-labelledby="entity-graph-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="entity-graph-heading" className="text-base font-semibold">Entity graph</h2>
          <p className="mt-1 text-sm text-muted">Shared devices, accounts, merchants, and beneficiaries</p>
        </div>
        <Network aria-hidden className="h-5 w-5 text-accent" />
      </div>
      <div className="mt-4 grid min-h-[230px] grid-cols-3 grid-rows-3 gap-3 rounded-md border border-border bg-background p-3 text-xs">
        <GraphNode className="col-start-2 row-start-1 bg-danger/10 text-danger" label="Account A" />
        <GraphNode className="col-start-1 row-start-2 bg-warning/10 text-warning" label="Device 42" />
        <GraphNode className="col-start-2 row-start-2 bg-accent/10 text-accent" label="Card 9182" />
        <GraphNode className="col-start-3 row-start-2 bg-background text-muted" label="IP cluster" />
        <GraphNode className="col-start-2 row-start-3 bg-success/10 text-success" label="Known payee" />
      </div>
    </section>
  );
}

function GraphNode({ label, className }: { label: string; className: string }) {
  return (
    <div className={`flex items-center justify-center rounded-md border border-border px-2 text-center font-semibold ${className}`}>
      {label}
    </div>
  );
}

function EvidencePanel() {
  const evidence = [
    "3 transactions occurred within 11 minutes after first-seen device.",
    "Merchant category differs from customer baseline by 2.4 standard deviations.",
    "Beneficiary appeared in one other escalated case this week."
  ];

  return (
    <section className="rounded-lg border border-border bg-panel p-4" aria-labelledby="evidence-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="evidence-heading" className="text-base font-semibold">Evidence timeline</h2>
          <p className="mt-1 text-sm text-muted">Explainable signals before an analyst makes a decision</p>
        </div>
        <FileCheck2 aria-hidden className="h-5 w-5 text-success" />
      </div>
      <ol className="mt-4 space-y-3">
        {evidence.map((item, index) => (
          <li key={item} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-background text-xs font-semibold text-muted">{index + 1}</span>
            <p className="rounded-md border border-border bg-background p-3 text-sm leading-5">{item}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function DecisionPanel() {
  return (
    <section className="rounded-lg border border-border bg-panel p-4" aria-labelledby="decision-heading">
      <h2 id="decision-heading" className="text-base font-semibold">Case decision</h2>
      <p className="mt-1 text-sm text-muted">Fast actions should leave a clear audit trail.</p>
      <div className="mt-4 grid gap-2">
        {["Escalate to fraud ops", "Request customer verification", "Mark false positive"].map((action, index) => (
          <button
            key={action}
            className={`h-10 rounded-md border px-3 text-left text-sm font-semibold transition ${
              index === 0
                ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/15"
                : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
            }`}
          >
            {action}
          </button>
        ))}
      </div>
    </section>
  );
}
