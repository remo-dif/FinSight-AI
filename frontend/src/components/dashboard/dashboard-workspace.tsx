"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import {
  FileUp,
  MessageSquareText,
  UserCheck,
  SlidersHorizontal,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatAmount, TransactionsTable } from "@/components/dashboard/transactions-table";
import { CaseWorkflow } from "@/components/dashboard/case-workflow";
import { Panel } from "@/components/ui/panel";
import {
  caseDetailQueryKey,
  caseListQueryKey,
  demoTransactions,
  fetchCaseDetail,
  fetchCases,
  InvestigationCase
} from "@/lib/api";
import type { InitialCaseQueue } from "@/lib/server-data";
import { useSessionStore } from "@/store/session";

const AuthPanel = dynamic(
  () => import("@/components/auth/auth-panel").then((module) => module.AuthPanel),
  { ssr: false, loading: DrawerPanelLoading }
);
const ChatPanel = dynamic(
  () => import("@/components/assistant/chat-panel").then((module) => module.ChatPanel),
  { ssr: false, loading: DrawerPanelLoading }
);
const UploadPanel = dynamic(
  () => import("@/components/uploads/upload-panel").then((module) => module.UploadPanel),
  { ssr: false, loading: DrawerPanelLoading }
);

type ToolDrawer = "session" | "copilot" | "upload" | null;

const filters = [
  { label: "Severity", values: ["High", "Elevated", "Review"] },
  { label: "SLA", values: ["Due < 1h", "Due today", "Breached"] },
  { label: "Owner", values: ["Unassigned", "Risk Ops", "Mine"] },
  { label: "Status", values: ["Needs evidence", "Escalated", "New"] }
];

export function DashboardWorkspace({ initialQueue }: { initialQueue?: InitialCaseQueue }) {
  const token = useSessionStore((state) => state.accessToken);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<ToolDrawer>(null);
  const hasServerSession = initialQueue?.status === "live" || initialQueue?.status === "unavailable";
  const hasSession = Boolean(token) || hasServerSession;
  const cases = useQuery({
    queryKey: caseListQueryKey(),
    queryFn: () => fetchCases(50),
    enabled: Boolean(token),
    initialData: initialQueue?.status === "live" ? initialQueue.cases ?? undefined : undefined,
    retry: false
  });

  const queueStatus = !hasSession
    ? "demo"
    : (!cases.data && initialQueue?.status === "unavailable") || cases.isError
      ? "error"
      : cases.isPending && !cases.data
        ? "loading"
        : "live";
  const activeCases = useMemo(
    () => hasSession ? cases.data ?? [] : demoTransactions,
    [hasSession, cases.data]
  );
  const selectedCase = useMemo(
    () =>
      activeCases.find((caseRecord) => caseRecord.id === selectedId) ??
      activeCases[0],
    [activeCases, selectedId]
  );

  return (
    <div className="space-y-4">
      <WorkspaceToolbar
        queueStatus={queueStatus}
        onRetry={() => void cases.refetch()}
        drawer={drawer}
        onDrawerChange={setDrawer}
      />

      <div className="grid gap-4 xl:grid-cols-[190px_minmax(0,1fr)_350px]">
        <QueueFilters caseCount={activeCases.length} />
        <div className="min-w-0">
          <TransactionsTable
            transactions={activeCases}
            selectedId={selectedCase?.id}
            onSelect={(caseRecord) => setSelectedId(caseRecord.id)}
          />
        </div>
        <AlertDetailPanel
          caseRecord={selectedCase}
          canMutate={Boolean(token)}
          onDrawerChange={setDrawer}
        />
      </div>

      {drawer ? <ContextDrawer drawer={drawer} onClose={() => setDrawer(null)} /> : null}
    </div>
  );
}

function WorkspaceToolbar({
  queueStatus,
  onRetry,
  drawer,
  onDrawerChange
}: {
  queueStatus: "demo" | "loading" | "live" | "error";
  onRetry: () => void;
  drawer: ToolDrawer;
  onDrawerChange: (drawer: ToolDrawer) => void;
}) {
  const tools: Array<{ id: Exclude<ToolDrawer, null>; label: string; icon: typeof UserCheck }> = [
    { id: "session", label: queueStatus !== "demo" ? "Session active" : "Sign in", icon: UserCheck },
    { id: "copilot", label: "Ask copilot", icon: MessageSquareText },
    { id: "upload", label: "Upload evidence", icon: FileUp }
  ];

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-panel px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted" role={queueStatus === "error" ? "status" : undefined}>
          {queueStatus === "demo"
            ? "Demo queue. Sign in to load live cases."
            : queueStatus === "loading"
              ? "Loading live cases..."
              : queueStatus === "error"
                ? "Live cases are unavailable. No demo cases are shown."
                : "Live queue is active. Select an alert to review evidence and record a decision."}
        </p>
        {queueStatus === "error" ? (
          <button type="button" className="text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
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

function QueueFilters({ caseCount }: { caseCount: number }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <aside className="rounded-lg border border-border bg-panel p-4" aria-label="Alert queue filters">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal aria-hidden className="h-4 w-4 text-muted xl:hidden" />
          <h2 className="text-sm font-semibold">Queue filters</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-background px-2 py-1 text-xs font-semibold text-muted">{caseCount} cases</span>
          <button
            type="button"
            className="h-8 rounded-md border border-border bg-white px-3 text-xs font-semibold text-muted hover:border-accent/60 hover:text-foreground xl:hidden"
            aria-expanded={isOpen}
            aria-controls="queue-filter-groups"
            onClick={() => setIsOpen((current) => !current)}
          >
            {isOpen ? "Hide" : "Filter"}
          </button>
        </div>
      </div>
      <div id="queue-filter-groups" className={`${isOpen ? "block" : "hidden"} mt-4 space-y-4 xl:block`}>
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
  caseRecord,
  canMutate,
  onDrawerChange
}: {
  caseRecord?: InvestigationCase;
  canMutate: boolean;
  onDrawerChange: (drawer: ToolDrawer) => void;
}) {
  const caseDetail = useQuery({
    queryKey: caseDetailQueryKey(caseRecord?.id ?? "none"),
    queryFn: () => {
      if (!caseRecord) throw new Error("A case must be selected");
      return fetchCaseDetail(caseRecord.id);
    },
    enabled: Boolean(caseRecord && canMutate),
    retry: false
  });

  return (
    <Panel as="section" className="p-0 xl:sticky xl:top-[96px] xl:max-h-[calc(100vh-120px)] xl:overflow-y-auto" aria-labelledby="selected-alert-heading">
      <div className="border-b border-border p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="selected-alert-heading" className="text-xs font-semibold uppercase tracking-wide text-muted">Selected alert</h2>
            <p className="mt-1 break-all text-xl font-semibold leading-tight">
              {caseRecord?.id ?? "No alert selected"}
            </p>
            <p className="mt-1 text-sm text-muted">{caseRecord?.merchant ?? "Select a row to review the case."}</p>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-2 text-sm">
          <SummaryItem label="Exposure" value={caseRecord ? formatAmount(caseRecord) : "--"} />
          <SummaryItem label="Source" value={caseRecord?.source ?? "--"} />
          <SummaryItem label="Status" value={caseRecord ? statusLabel(caseRecord.status) : "--"} />
        </dl>
      </div>

      <div className="space-y-5 p-4">
        <section aria-labelledby="signal-heading">
          <h3 id="signal-heading" className="text-sm font-semibold">Primary signal</h3>
          <p className="mt-1 text-base font-semibold">{caseRecord?.category ?? "Awaiting selection"}</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            {caseRecord?.description ?? "Select a case to review its transaction context and record an investigation."}
          </p>
        </section>

        <section aria-labelledby="evidence-heading">
          <div className="flex items-center justify-between gap-3">
            <h3 id="evidence-heading" className="text-sm font-semibold">Transaction context</h3>
            <button
              type="button"
              className="text-sm font-semibold text-accent underline-offset-4 hover:underline"
              onClick={() => onDrawerChange("upload")}
            >
              Add evidence
            </button>
          </div>
          <p className="mt-3 rounded-md border border-border bg-background p-3 text-sm leading-5">
            {caseRecord
              ? `${caseRecord.category} classification from ${caseRecord.source} source.`
              : "Transaction details appear when a case is selected."}
          </p>
        </section>

        {caseRecord ? (
          <CaseWorkflow
            key={`${caseRecord.id}:${canMutate}`}
            caseRecord={caseRecord}
            detail={caseDetail.data}
            canMutate={canMutate}
            isDetailLoading={caseDetail.isLoading}
            isDetailError={caseDetail.isError}
            onRetryDetail={() => void caseDetail.refetch()}
          />
        ) : null}
      </div>
    </Panel>
  );
}

function SummaryItem({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-panel p-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-1 break-all font-semibold ${tone === "danger" ? "text-danger" : ""}`}>{value}</dd>
    </div>
  );
}

function ContextDrawer({ drawer, onClose }: { drawer: Exclude<ToolDrawer, null>; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const titles = {
    session: "Analyst session",
    copilot: "Investigation copilot",
    upload: "Evidence ingestion"
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();

    return () => triggerRef.current?.focus();
  }, []);
  return (
    <dialog
      ref={dialogRef}
      className="m-0 ml-auto h-full max-h-none w-[min(440px,calc(100%-1.5rem))] overflow-y-auto rounded-l-lg border border-border bg-background p-0 text-foreground shadow-soft backdrop:bg-foreground/30"
      aria-labelledby="context-drawer-heading"
      onClose={onClose}
    >
        <div className="flex items-center justify-between gap-3 border-b border-border bg-panel px-4 py-3">
          <h2 id="context-drawer-heading" className="text-base font-semibold">{titles[drawer]}</h2>
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-white text-muted hover:text-foreground"
            onClick={() => dialogRef.current?.close()}
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
    </dialog>
  );
}

function DrawerPanelLoading() {
  return <div className="h-48 animate-pulse rounded-lg bg-border/50" role="status"><span className="sr-only">Loading panel</span></div>;
}

function statusLabel(status: InvestigationCase["status"]) {
  return {
    new: "New",
    needs_evidence: "Needs evidence",
    escalated: "Escalated",
    resolved: "Resolved"
  }[status];
}
