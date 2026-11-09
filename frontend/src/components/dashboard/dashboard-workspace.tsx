"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  FileUp,
  MessageSquareText,
  UserCheck,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatAmount, TransactionsTable } from "@/components/dashboard/transactions-table";
import { CaseWorkflow } from "@/components/dashboard/case-workflow";
import { Panel } from "@/components/ui/panel";
import {
  ApiError,
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

function useCaseQueue(initialQueue?: InitialCaseQueue) {
  const token = useSessionStore((state) => state.accessToken);
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
  const sessionGeneration = useSessionStore((state) => state.sessionGeneration);
  // SSR data belongs only to the session that rendered this page.
  const serverCases = sessionGeneration === 0 && initialQueue?.status === "live"
    ? initialQueue.cases ?? undefined
    : undefined;
  const hasServerSession = Boolean(serverCases) || initialQueue?.status === "unavailable";
  const hasSession = Boolean(token) || hasServerSession;
  const cases = useQuery({
    queryKey: caseListQueryKey(),
    queryFn: () => fetchCases(50),
    enabled: Boolean(token),
    initialData: serverCases,
    retry: false
  });

  const queueStatus: "demo" | "loading" | "live" | "error" = !hasSession
    ? "demo"
    : (!cases.data && initialQueue?.status === "unavailable") || cases.isError
      ? "error"
      : cases.isPending && !cases.data
        ? "loading"
        : "live";
  const activeCases = useMemo(
    () => hasSession ? (token ? cases.data : serverCases) ?? [] : demoTransactions,
    [hasSession, token, cases.data, serverCases]
  );
  return { token, cases, queueStatus, activeCases, userDataEpoch };
}

export function TriageWorkspace({ initialQueue }: { initialQueue?: InitialCaseQueue }) {
  const { cases, queueStatus, activeCases } = useCaseQueue(initialQueue);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<ToolDrawer>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);
  const selectedCase = useMemo(
    () => activeCases.find((caseRecord) => caseRecord.id === selectedId) ?? activeCases[0],
    [activeCases, selectedId]
  );

  return <div className="space-y-4">
    <QueueStatus status={queueStatus} onRetry={() => void cases.refetch()} onSession={(trigger) => { drawerTriggerRef.current = trigger; setDrawer("session"); }} />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0">
        <TransactionsTable
          transactions={activeCases}
          selectedId={selectedCase?.id}
          queueStatus={queueStatus === "loading" ? "loading" : queueStatus === "error" ? "error" : "ready"}
          onSelect={(caseRecord) => setSelectedId(caseRecord.id)}
        />
      </div>
      <Panel as="aside" className="h-fit p-4 xl:sticky xl:top-[96px]" aria-labelledby="triage-next-heading">
        <h2 id="triage-next-heading" className="text-base font-semibold">Next investigation</h2>
        {selectedCase ? <>
          <p className="mt-3 break-all text-lg font-semibold">{selectedCase.id}</p>
          <p className="mt-1 text-sm text-muted">{selectedCase.merchant}</p>
          <dl className="mt-4 space-y-2 text-sm"><SummaryItem label="Status" value={statusLabel(selectedCase.status)} /><SummaryItem label="Assignment" value={selectedCase.assignee_name ?? "Unassigned"} /></dl>
          <Link className="mt-4 inline-flex min-h-10 items-center rounded-md bg-accent px-4 text-sm font-semibold text-white" href={`/cases?case=${encodeURIComponent(selectedCase.id)}`}>Open case</Link>
        </> : <p className="mt-3 text-sm text-muted">Select an alert to choose the next investigation.</p>}
      </Panel>
    </div>
    {drawer ? <ContextDrawer drawer={drawer} onClose={() => setDrawer(null)} triggerRef={drawerTriggerRef} /> : null}
  </div>;
}

export function CasesWorkspace({ initialQueue, initialSelectedId }: { initialQueue?: InitialCaseQueue; initialSelectedId?: string }) {
  const { token, cases, queueStatus, activeCases, userDataEpoch } = useCaseQueue(initialQueue);
  // Explicit navigation is a request to resolve an ID under the current session.
  // A case selected from the loaded queue belongs to that queue's session.
  const [selection, setSelection] = useState<{ id: string | null; epoch: number | null }>({
    id: initialSelectedId ?? null,
    epoch: null
  });
  const selectedId = selection.epoch === null || selection.epoch === userDataEpoch ? selection.id : null;
  const [focusDetailRequested, setFocusDetailRequested] = useState(Boolean(initialSelectedId));
  const [drawer, setDrawer] = useState<ToolDrawer>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);
  const queuedCase = useMemo(() => activeCases.find((item) => item.id === selectedId), [activeCases, selectedId]);
  const requestedCase = useQuery({
    queryKey: caseDetailQueryKey(selectedId ?? "none"),
    queryFn: () => {
      if (!selectedId) throw new Error("A case ID is required");
      return fetchCaseDetail(selectedId);
    },
    enabled: Boolean(selectedId && !queuedCase && token),
    retry: false
  });
  const selectedCase = selectedId ? queuedCase ?? requestedCase.data : activeCases[0];

  useEffect(() => {
    function syncFromHistory() {
      const caseId = new URL(window.location.href).searchParams.get("case");
      setSelection({ id: caseId, epoch: null });
      setFocusDetailRequested(Boolean(caseId));
    }
    window.addEventListener("popstate", syncFromHistory);
    return () => window.removeEventListener("popstate", syncFromHistory);
  }, []);

  useEffect(() => {
    if (!focusDetailRequested || !selectedId) return;
    const heading = detailHeadingRef.current;
    if (heading) {
      heading.focus({ preventScroll: true });
      const headerBottom = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
      const headingTop = heading.getBoundingClientRect().top;
      window.scrollBy({ top: headingTop - headerBottom - 16 });
    }
    setFocusDetailRequested(false);
  }, [focusDetailRequested, selectedId]);

  function changeDrawer(next: ToolDrawer, trigger?: HTMLElement) {
    if (next && trigger) drawerTriggerRef.current = trigger;
    setDrawer(next);
  }

  return (
    <div className="space-y-4">
      <WorkspaceToolbar
        queueStatus={queueStatus}
        onRetry={() => void cases.refetch()}
        drawer={drawer}
        onDrawerChange={changeDrawer}
      />

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <CaseNavigator cases={activeCases} selectedId={selectedCase?.id} status={queueStatus} onRetry={() => void cases.refetch()} onSelect={(caseRecord) => {
          setSelection({ id: caseRecord.id, epoch: userDataEpoch });
          setFocusDetailRequested(true);
          window.history.pushState(null, "", `/cases?case=${encodeURIComponent(caseRecord.id)}`);
        }} />
        {selectedCase ? (
          <AlertDetailPanel
            caseRecord={selectedCase}
            canMutate={Boolean(token)}
            onDrawerChange={changeDrawer}
            headingRef={detailHeadingRef}
          />
        ) : (
          <RequestedCaseState
            caseId={selectedId}
            isLoading={queueStatus === "loading" || requestedCase.fetchStatus === "fetching"}
            error={requestedCase.error}
            onRetry={() => void requestedCase.refetch()}
            headingRef={detailHeadingRef}
          />
        )}
      </div>

      {drawer ? (
        <ContextDrawer
          drawer={drawer}
          onClose={() => setDrawer(null)}
          triggerRef={drawerTriggerRef}
        />
      ) : null}
    </div>
  );
}

function RequestedCaseState({
  caseId,
  isLoading,
  error,
  onRetry,
  headingRef
}: {
  caseId: string | null;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
  headingRef: { current: HTMLHeadingElement | null };
}) {
  const isNotFound = error instanceof ApiError && error.status === 404;

  return (
    <Panel as="section" className="h-fit p-6" aria-labelledby="selected-alert-heading">
      <h2 ref={headingRef} id="selected-alert-heading" tabIndex={-1} className="scroll-mt-28 text-xs font-semibold uppercase tracking-wide text-muted">
        Requested case
      </h2>
      <p className="mt-2 break-all text-xl font-semibold">{caseId ?? "No case selected"}</p>
      {isLoading ? <p className="mt-4 text-sm text-muted" role="status">Loading the requested case...</p> : null}
      {!isLoading && isNotFound ? (
        <p className="mt-4 text-sm text-danger" role="alert">This case was not found or is not available to your account.</p>
      ) : null}
      {!isLoading && error && !isNotFound ? (
        <div className="mt-4 text-sm" role="alert">
          <p className="text-danger">The requested case could not be loaded.</p>
          <button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>Retry</button>
        </div>
      ) : null}
      {!isLoading && !error ? (
        <p className="mt-4 text-sm text-muted">This case is not in the current list. Sign in to check whether it is available to your account.</p>
      ) : null}
    </Panel>
  );
}

function QueueStatus({ status, onRetry, onSession }: { status: "demo" | "loading" | "live" | "error"; onRetry: () => void; onSession: (trigger: HTMLElement) => void }) {
  return <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-panel px-4 py-3">
    <p className="text-sm text-muted" role={status === "error" ? "alert" : "status"}>{status === "demo" ? "Demo queue. Sign in to load live cases." : status === "loading" ? "Loading live cases..." : status === "error" ? "Live cases are unavailable. No demo cases are shown." : "Live queue is active. Choose what needs attention next."}</p>
    {status === "error" ? <button type="button" className="text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={onRetry}>Retry</button> : null}
    <button type="button" className="ml-auto inline-flex min-h-9 items-center rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted hover:border-accent/60 hover:text-foreground" onClick={(event) => onSession(event.currentTarget)}>{status === "demo" ? "Sign in" : "Session active"}</button>
  </div>;
}

function CaseNavigator({ cases, selectedId, status, onRetry, onSelect }: { cases: InvestigationCase[]; selectedId?: string; status: "demo" | "loading" | "live" | "error"; onRetry: () => void; onSelect: (item: InvestigationCase) => void }) {
  return <Panel as="nav" className="h-fit p-3 xl:sticky xl:top-[96px]" aria-label="Case navigator">
    <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">Cases</h2><span className="text-xs text-muted">{cases.length}</span></div>
    {status === "loading" && cases.length === 0 ? <p className="mt-3 text-sm text-muted" role="status">Loading cases...</p> : null}
    {status === "error" && cases.length === 0 ? <div className="mt-3 text-sm" role="alert"><p className="text-danger">Cases are unavailable.</p><button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>Retry</button></div> : null}
    {status === "error" && cases.length > 0 ? <div className="mt-3 text-sm" role="status"><p className="font-semibold text-warning">Refresh failed. Showing the most recently loaded cases.</p><button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>Retry</button></div> : null}
    {status !== "loading" && status !== "error" && cases.length === 0 ? <p className="mt-3 text-sm text-muted">No cases are available.</p> : null}
    <ul className="mt-3 space-y-2">{cases.map((item) => <li key={item.id}><button type="button" className={`w-full rounded-md border p-3 text-left transition ${item.id === selectedId ? "border-accent bg-accent/10" : "border-border bg-white hover:border-accent/60"}`} aria-current={item.id === selectedId ? "true" : undefined} onClick={() => onSelect(item)}><span className="block break-all text-sm font-semibold">{item.id}</span><span className="mt-1 block truncate text-xs text-muted">{item.merchant} · {statusLabel(item.status)}</span></button></li>)}</ul>
  </Panel>;
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
  onDrawerChange: (drawer: ToolDrawer, trigger?: HTMLElement) => void;
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
              onClick={(event) => onDrawerChange(active ? null : tool.id, event.currentTarget)}
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

function AlertDetailPanel({
  caseRecord,
  canMutate,
  onDrawerChange,
  headingRef
}: {
  caseRecord?: InvestigationCase;
  canMutate: boolean;
  onDrawerChange: (drawer: ToolDrawer, trigger?: HTMLElement) => void;
  headingRef: { current: HTMLHeadingElement | null };
}) {
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
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
    <Panel id="selected-alert-panel" as="section" className="p-0 xl:sticky xl:top-[96px] xl:max-h-[calc(100vh-120px)] xl:overflow-y-auto" aria-labelledby="selected-alert-heading">
      <div className="border-b border-border p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 ref={headingRef} id="selected-alert-heading" tabIndex={-1} className="scroll-mt-28 text-xs font-semibold uppercase tracking-wide text-muted">Selected alert</h2>
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
              onClick={(event) => onDrawerChange("upload", event.currentTarget)}
            >
              Upload to Document Library
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
            key={`${caseRecord.id}:${canMutate}:${userDataEpoch}`}
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

function ContextDrawer({
  drawer,
  onClose,
  triggerRef
}: {
  drawer: Exclude<ToolDrawer, null>;
  onClose: () => void;
  triggerRef: { current: HTMLElement | null };
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titles = {
    session: "Analyst session",
    copilot: "Investigation copilot",
    upload: "Evidence ingestion"
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();

    return () => {
      triggerRef.current?.focus();
      triggerRef.current = null;
    };
  }, [triggerRef]);
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
