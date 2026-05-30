"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDownUp, CalendarClock, WalletCards } from "lucide-react";
import { MetricCard } from "@/components/dashboard/metric-card";
import { SpendingChart, SpendingChartDatum } from "@/components/dashboard/spending-chart";
import { TransactionsTable } from "@/components/dashboard/transactions-table";
import { demoTransactions, fetchMonthlySummary, fetchTransactions, Transaction } from "@/lib/api";
import { useSessionStore } from "@/store/session";

const COLORS = ["#0b84a5", "#16a064", "#f59e0b", "#dc3055", "#6f4bd8", "#64748b"];

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

function money(value: string | number) {
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
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
    .map(([name, value], index) => ({ name, value, color: COLORS[index % COLORS.length] }));
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
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Net Cash Flow" value={money(activeSummary.net_cash_flow)} detail={`${activeSummary.month} summary`} icon={ArrowDownUp} tone="success" />
        <MetricCard label="Spending" value={money(activeSummary.spending)} detail="Current tracked spend" icon={WalletCards} tone="accent" />
        <MetricCard label="Anomalies" value="Ask" detail="Use the assistant for review" icon={AlertTriangle} tone="danger" />
        <MetricCard label="Recurring" value="Ask" detail="Detected through chat tools" icon={CalendarClock} tone="warning" />
      </div>
      <div className="grid items-start gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <SpendingChart data={categoryData(activeTransactions)} />
        <TransactionsTable transactions={activeTransactions} />
      </div>
    </>
  );
}
