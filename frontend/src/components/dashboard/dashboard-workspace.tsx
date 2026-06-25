"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Fingerprint,
  Gavel,
  Network,
  ShieldAlert,
  UserCheck
} from "lucide-react";
import { MetricCard } from "@/components/dashboard/metric-card";
import { SpendingChart, SpendingChartDatum } from "@/components/dashboard/spending-chart";
import { formatAmount, riskFor, TransactionsTable } from "@/components/dashboard/transactions-table";
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
  const selectedTransaction = useMemo(
    () =>
      activeTransactions.find((transaction) => transaction.id === selectedId) ??
      activeTransactions[0],
    [activeTransactions, selectedId]
  );
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
        <TransactionsTable
          transactions={activeTransactions}
          selectedId={selectedTransaction?.id}
          onSelect={(transaction) => setSelectedId(transaction.id)}
        />
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-1">
          <SpendingChart data={categoryData(activeTransactions)} />
          <EntityGraphPanel transaction={selectedTransaction} />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <EvidencePanel transaction={selectedTransaction} />
        <DecisionPanel transaction={selectedTransaction} />
      </div>
    </>
  );
}

function EntityGraphPanel({ transaction }: { transaction?: Transaction }) {
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
        <GraphNode className="col-start-2 row-start-1 bg-danger/10 text-danger" label={transaction?.id ?? "Case"} />
        <GraphNode className="col-start-1 row-start-2 bg-warning/10 text-warning" label="Device 42" />
        <GraphNode className="col-start-2 row-start-2 bg-accent/10 text-accent" label="Card 9182" />
        <GraphNode className="col-start-3 row-start-2 bg-background text-muted" label="IP cluster" />
        <GraphNode className="col-start-2 row-start-3 bg-success/10 text-success" label={transaction?.merchant ?? "Known payee"} />
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

function evidenceFor(transaction?: Transaction) {
  if (!transaction) {
    return [
      "No alert selected.",
      "Select a queue item to review signal evidence.",
      "Decision controls will update with the selected case."
    ];
  }
  return [
    transaction.description,
    `${transaction.category} triggered on ${transaction.source} evidence with ${formatAmount(transaction)} exposure.`,
    "Related entity appeared in one other escalated case this week."
  ];
}

function EvidencePanel({ transaction }: { transaction?: Transaction }) {
  const evidence = evidenceFor(transaction);
  const risk = transaction ? riskFor(transaction) : null;

  return (
    <section className="rounded-lg border border-border bg-panel p-4" aria-labelledby="evidence-heading">
      <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="evidence-heading" className="text-base font-semibold">Evidence timeline</h2>
          <p className="mt-1 text-sm text-muted">
            {transaction ? `${transaction.id} · ${transaction.merchant}` : "Explainable signals before an analyst makes a decision"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {risk ? (
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ${risk.className}`}>
              Risk {risk.score}
            </span>
          ) : null}
          <FileCheck2 aria-hidden className="h-5 w-5 text-success" />
        </div>
      </div>
      <ol className="mt-4 grid gap-3">
        {evidence.map((item, index) => (
          <li key={item} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-background text-xs font-semibold text-muted">
              {index + 1}
            </span>
            <div className="rounded-md border border-border bg-background p-3">
              <p className="text-sm leading-5">{item}</p>
              <p className="mt-2 text-xs font-medium text-muted">
                {index === 0 ? "Source event" : index === 1 ? "Risk model" : "Entity correlation"}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function DecisionPanel({ transaction }: { transaction?: Transaction }) {
  const actions = [
    { label: "Escalate to fraud ops", icon: ShieldAlert, tone: "danger" },
    { label: "Request customer verification", icon: UserCheck, tone: "accent" },
    { label: "Mark false positive", icon: CheckCircle2, tone: "success" }
  ] as const;

  return (
    <section className="rounded-lg border border-border bg-panel p-4" aria-labelledby="decision-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="decision-heading" className="text-base font-semibold">Case decision</h2>
          <p className="mt-1 text-sm text-muted">
            {transaction ? `${transaction.id} action queue` : "Fast actions should leave a clear audit trail."}
          </p>
        </div>
        <Fingerprint aria-hidden className="h-5 w-5 text-accent" />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-2 rounded-md border border-border bg-background p-3 text-xs">
        <div>
          <dt className="font-semibold uppercase tracking-wide text-muted">Exposure</dt>
          <dd className="mt-1 font-semibold">{transaction ? formatAmount(transaction) : "$0.00"}</dd>
        </div>
        <div>
          <dt className="font-semibold uppercase tracking-wide text-muted">Evidence</dt>
          <dd className="mt-1 font-semibold">3 signals</dd>
        </div>
      </dl>
      <div className="mt-4 grid gap-2">
        {actions.map((action, index) => {
          const Icon = action.icon;
          const selected = index === 0;
          return (
          <button
            key={action.label}
            className={`flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm font-semibold transition ${
              selected
                ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/15"
                : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
            }`}
            aria-pressed={selected}
          >
            <Icon aria-hidden className="h-4 w-4 shrink-0" />
            {action.label}
          </button>
          );
        })}
      </div>
      <p className="mt-4 rounded-md border border-border bg-background p-3 text-xs leading-5 text-muted">
        Decision preview: selected action will write an audit event with analyst, case id, risk score, and supporting evidence references.
      </p>
    </section>
  );
}
