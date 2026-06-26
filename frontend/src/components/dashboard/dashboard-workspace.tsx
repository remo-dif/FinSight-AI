"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileUp,
  History,
  MessageSquareText,
  ShieldAlert,
  UserCheck,
  X
} from "lucide-react";
import { useMemo, useState } from "react";
import { ChatPanel } from "@/components/assistant/chat-panel";
import { AuthPanel } from "@/components/auth/auth-panel";
import { formatAmount, riskFor, TransactionsTable } from "@/components/dashboard/transactions-table";
import { Panel } from "@/components/ui/panel";
import { UploadPanel } from "@/components/uploads/upload-panel";
import { demoTransactions, fetchMonthlySummary, fetchTransactions, Transaction } from "@/lib/api";
import { useSessionStore } from "@/store/session";

type ToolDrawer = "session" | "copilot" | "upload" | null;

const filters = [
  { label: "Severity", values: ["High", "Elevated", "Review"] },
  { label: "SLA", values: ["Due < 1h", "Due today", "Breached"] },
  { label: "Owner", values: ["Unassigned", "Risk Ops", "Mine"] },
  { label: "Status", values: ["Needs evidence", "Escalated", "New"] }
];

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

export function DashboardWorkspace() {
  const token = useSessionStore((state) => state.accessToken);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<ToolDrawer>(null);
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

  return (
    <div className="space-y-4">
      <WorkspaceToolbar
        hasSession={Boolean(token)}
        isUsingFallback={!token || summary.isError || transactions.isError}
        drawer={drawer}
        onDrawerChange={setDrawer}
      />

      <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)_400px]">
        <QueueFilters />
        <section aria-labelledby="alert-queue-heading" className="min-w-0">
          <TransactionsTable
            transactions={activeTransactions}
            selectedId={selectedTransaction?.id}
            onSelect={(transaction) => setSelectedId(transaction.id)}
          />
        </section>
        <AlertDetailPanel transaction={selectedTransaction} onDrawerChange={setDrawer} />
      </div>

      {drawer ? <ContextDrawer drawer={drawer} onClose={() => setDrawer(null)} /> : null}
    </div>
  );
}

function WorkspaceToolbar({
  hasSession,
  isUsingFallback,
  drawer,
  onDrawerChange
}: {
  hasSession: boolean;
  isUsingFallback: boolean;
  drawer: ToolDrawer;
  onDrawerChange: (drawer: ToolDrawer) => void;
}) {
  const tools: Array<{ id: Exclude<ToolDrawer, null>; label: string; icon: typeof UserCheck }> = [
    { id: "session", label: hasSession ? "Session active" : "Sign in", icon: UserCheck },
    { id: "copilot", label: "Ask copilot", icon: MessageSquareText },
    { id: "upload", label: "Upload evidence", icon: FileUp }
  ];

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-panel px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
      <p className="text-sm text-muted">
        {isUsingFallback
          ? "Showing demo alerts. Sign in when you need live data."
          : "Live queue is active. Select an alert to review evidence and record a decision."}
      </p>
      <div className="flex flex-wrap gap-2">
        {tools.map((tool) => {
          const Icon = tool.icon;
          const active = drawer === tool.id;
          return (
            <button
              key={tool.id}
              type="button"
              className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-semibold transition ${
                active
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
              }`}
              onClick={() => onDrawerChange(active ? null : tool.id)}
              aria-pressed={active}
            >
              <Icon aria-hidden className="h-4 w-4" />
              {tool.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function QueueFilters() {
  return (
    <aside className="rounded-lg border border-border bg-panel p-4" aria-label="Alert queue filters">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">Queue filters</h2>
        <span className="rounded-md bg-danger/10 px-2 py-1 text-xs font-semibold text-danger">12 open</span>
      </div>
      <div className="mt-4 space-y-4">
        {filters.map((group) => (
          <fieldset key={group.label}>
            <legend className="text-xs font-semibold uppercase tracking-wide text-muted">{group.label}</legend>
            <div className="mt-2 space-y-1">
              {group.values.map((value, index) => (
                <label key={value} className="flex min-h-8 items-center gap-2 rounded-md px-2 text-sm text-muted hover:bg-background hover:text-foreground">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                    defaultChecked={group.label === "Severity" && index === 0}
                  />
                  {value}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>
    </aside>
  );
}

function AlertDetailPanel({
  transaction,
  onDrawerChange
}: {
  transaction?: Transaction;
  onDrawerChange: (drawer: ToolDrawer) => void;
}) {
  const risk = transaction ? riskFor(transaction) : null;
  const evidence = evidenceFor(transaction);

  return (
    <Panel className="sticky top-[96px] max-h-[calc(100vh-120px)] overflow-y-auto p-0" aria-labelledby="selected-alert-heading">
      <div className="border-b border-border p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="selected-alert-heading" className="text-xs font-semibold uppercase tracking-wide text-muted">Selected alert</h2>
            <p className="mt-1 text-xl font-semibold leading-tight">
              {transaction?.id ?? "No alert selected"}
            </p>
            <p className="mt-1 text-sm text-muted">{transaction?.merchant ?? "Select a row to review the case."}</p>
          </div>
          {risk ? (
            <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${risk.className}`}>
              {risk.label} {risk.score}
            </span>
          ) : null}
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
          <SummaryItem label="Exposure" value={transaction ? formatAmount(transaction) : "$0.00"} />
          <SummaryItem label="SLA" value="42m" tone="danger" />
          <SummaryItem label="Source" value={transaction?.source ?? "--"} />
          <SummaryItem label="Status" value="Needs evidence" />
        </dl>
      </div>

      <div className="space-y-5 p-4">
        <section aria-labelledby="signal-heading">
          <h3 id="signal-heading" className="text-sm font-semibold">Primary signal</h3>
          <p className="mt-1 text-base font-semibold">{transaction?.category ?? "Awaiting selection"}</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            {transaction?.description ?? "Select an alert to review evidence, entity links, and recommended action."}
          </p>
        </section>

        <section aria-labelledby="evidence-heading">
          <div className="flex items-center justify-between gap-3">
            <h3 id="evidence-heading" className="text-sm font-semibold">Evidence summary</h3>
            <button
              type="button"
              className="text-sm font-semibold text-accent underline-offset-4 hover:underline"
              onClick={() => onDrawerChange("upload")}
            >
              Add evidence
            </button>
          </div>
          <ol className="mt-3 space-y-2">
            {evidence.map((item, index) => (
              <li key={item} className="grid grid-cols-[24px_minmax(0,1fr)] gap-2 rounded-md border border-border bg-background p-3 text-sm leading-5">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-panel text-xs font-semibold text-muted">
                  {index + 1}
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="decision-heading">
          <h3 id="decision-heading" className="text-sm font-semibold">Decision</h3>
          <div className="mt-3 grid gap-2">
            <DecisionButton icon={ShieldAlert} label="Escalate to fraud ops" selected />
            <DecisionButton icon={UserCheck} label="Request customer verification" />
            <DecisionButton icon={CheckCircle2} label="Mark false positive" />
          </div>
        </section>

        <details className="rounded-md border border-border bg-background p-3">
          <summary className="cursor-pointer text-sm font-semibold">Audit preview</summary>
          <ol className="mt-3 space-y-2 text-sm text-muted">
            <li className="flex gap-2"><History aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> Analyst reviewed evidence</li>
            <li className="flex gap-2"><Clock3 aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> Customer verification queued</li>
            <li className="flex gap-2"><AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> Disposition requires reason code</li>
          </ol>
        </details>

        <details className="rounded-md border border-border bg-background p-3">
          <summary className="cursor-pointer text-sm font-semibold">Entity snapshot</summary>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <SummaryItem label="Device" value="Device 42" />
            <SummaryItem label="Card" value="9182" />
            <SummaryItem label="Merchant" value={transaction?.merchant ?? "--"} />
            <SummaryItem label="Signals" value="3 linked" />
          </dl>
        </details>
      </div>
    </Panel>
  );
}

function SummaryItem({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  return (
    <div className="rounded-md border border-border bg-panel p-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-1 truncate font-semibold ${tone === "danger" ? "text-danger" : ""}`}>{value}</dd>
    </div>
  );
}

function DecisionButton({
  icon: Icon,
  label,
  selected = false
}: {
  icon: typeof ShieldAlert;
  label: string;
  selected?: boolean;
}) {
  return (
    <button
      type="button"
      className={`flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm font-semibold transition ${
        selected
          ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/15"
          : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
      }`}
      aria-pressed={selected}
    >
      <Icon aria-hidden className="h-4 w-4 shrink-0" />
      {label}
    </button>
  );
}

function ContextDrawer({ drawer, onClose }: { drawer: Exclude<ToolDrawer, null>; onClose: () => void }) {
  const titles = {
    session: "Analyst session",
    copilot: "Investigation copilot",
    upload: "Evidence ingestion"
  };

  return (
    <div className="fixed inset-0 z-40 bg-foreground/20 p-3 sm:p-6" role="presentation">
      <aside
        className="ml-auto flex h-full w-full max-w-[440px] flex-col overflow-y-auto rounded-lg border border-border bg-background shadow-soft"
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-drawer-heading"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border bg-panel px-4 py-3">
          <h2 id="context-drawer-heading" className="text-base font-semibold">{titles[drawer]}</h2>
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-white text-muted hover:text-foreground"
            onClick={onClose}
            aria-label="Close panel"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 p-4">
          {drawer === "session" ? <AuthPanel /> : null}
          {drawer === "copilot" ? <ChatPanel /> : null}
          {drawer === "upload" ? <UploadPanel /> : null}
        </div>
      </aside>
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
