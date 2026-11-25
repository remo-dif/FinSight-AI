"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  FileUp,
  Inbox,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  TriangleAlert,
  UserCheck,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatAmount, TransactionsTable } from "@/components/dashboard/transactions-table";
import { CaseWorkflow } from "@/components/dashboard/case-workflow";
import { Button } from "@/components/ui/button";
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
import { localizePath, useLocale, useTranslations } from "@/i18n/context";

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

function useLoginHref() {
  const locale = useLocale();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  const destination = `${pathname}${query ? `?${query}` : ""}`;
  return `${localizePath("/login", locale)}?returnTo=${encodeURIComponent(destination)}`;
}

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
    // Partition authenticated data by ownership. Prefix invalidations still
    // match this key, while an account change cannot retain the prior queue.
    queryKey: [...caseListQueryKey(), userDataEpoch],
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
  const t = useTranslations();
  const locale = useLocale();
  const loginHref = useLoginHref();
  const { cases, queueStatus, activeCases } = useCaseQueue(initialQueue);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<ToolDrawer>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);
  const selectedCase = useMemo(
    () => activeCases.find((caseRecord) => caseRecord.id === selectedId) ?? activeCases[0],
    [activeCases, selectedId]
  );

  return <div className="space-y-4">
    <QueueStatus status={queueStatus} loginHref={loginHref} onRetry={() => void cases.refetch()} onSession={(trigger) => { drawerTriggerRef.current = trigger; setDrawer("session"); }} />
    {activeCases.length === 0 && queueStatus !== "demo" ? (
      <QueueStatePanel workspace="triage" status={queueStatus} onRetry={() => void cases.refetch()} />
    ) : <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0">
        <TransactionsTable
          transactions={activeCases}
          selectedId={selectedCase?.id}
          queueStatus={queueStatus === "loading" ? "loading" : queueStatus === "error" ? "error" : "ready"}
          onSelect={(caseRecord) => setSelectedId(caseRecord.id)}
        />
      </div>
      <Panel as="aside" className="h-fit p-4 xl:sticky xl:top-[96px]" aria-labelledby="triage-next-heading">
        <h2 id="triage-next-heading" className="text-base font-semibold">{t("nextInvestigation")}</h2>
        {selectedCase ? <>
          <p className="mt-3 break-all text-lg font-semibold">{selectedCase.id}</p>
          <p className="mt-1 text-sm text-muted">{selectedCase.merchant}</p>
          <dl className="mt-4 space-y-2 text-sm"><SummaryItem label={t("status")} value={statusLabel(selectedCase.status, t)} /><SummaryItem label={t("assignment")} value={selectedCase.assignee_name ?? t("unassigned")} /></dl>
          <Link className="mt-4 inline-flex min-h-10 items-center rounded-md bg-accent px-4 text-sm font-semibold text-white" href={`${locale === "en" ? "" : `/${locale}`}/cases?case=${encodeURIComponent(selectedCase.id)}` as never}>{t("openCase")}</Link>
        </> : <p className="mt-3 text-sm text-muted">{t("selectAlert")}</p>}
      </Panel>
    </div>}
    {drawer ? <ContextDrawer drawer={drawer} onClose={() => setDrawer(null)} triggerRef={drawerTriggerRef} /> : null}
  </div>;
}

export function CasesWorkspace({ initialQueue, initialSelectedId }: { initialQueue?: InitialCaseQueue; initialSelectedId?: string }) {
  const locale = useLocale();
  const loginHref = useLoginHref();
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
  const navigatorHeadingRef = useRef<HTMLHeadingElement>(null);
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

  function returnToCaseList() {
    const heading = navigatorHeadingRef.current;
    if (!heading) return;
    heading.focus({ preventScroll: true });
    const headerBottom = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
    window.scrollBy({ top: heading.getBoundingClientRect().top - headerBottom - 16 });
  }

  const showQueueState = !selectedId && activeCases.length === 0 && queueStatus !== "demo";

  return (
    <div className="space-y-4">
      <WorkspaceToolbar
        queueStatus={queueStatus}
        onRetry={() => void cases.refetch()}
        drawer={drawer}
        loginHref={loginHref}
        hasCaseContext={!showQueueState}
        onDrawerChange={changeDrawer}
      />

      {showQueueState ? (
        <QueueStatePanel workspace="cases" status={queueStatus} onRetry={() => void cases.refetch()} />
      ) : <div className="grid min-w-0 gap-4 md:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]">
        <CaseNavigator headingRef={navigatorHeadingRef} cases={activeCases} selectedId={selectedCase?.id} status={queueStatus} onRetry={() => void cases.refetch()} onSelect={(caseRecord) => {
          setSelection({ id: caseRecord.id, epoch: userDataEpoch });
          setFocusDetailRequested(true);
          window.history.pushState(null, "", localizePath(`/cases?case=${encodeURIComponent(caseRecord.id)}`, locale));
        }} />
        {selectedCase ? (
          <AlertDetailPanel
            caseRecord={selectedCase}
            canMutate={Boolean(token)}
            onDrawerChange={changeDrawer}
            headingRef={detailHeadingRef}
            onReturnToList={returnToCaseList}
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
      </div>}

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
  const t = useTranslations();
  const isNotFound = error instanceof ApiError && error.status === 404;

  return (
    <Panel as="section" className="h-fit p-6" aria-labelledby="selected-alert-heading">
      <h2 ref={headingRef} id="selected-alert-heading" tabIndex={-1} className="scroll-mt-28 text-xs font-semibold uppercase tracking-wide text-muted">
        {t("requestedCase")}
      </h2>
      <p className="mt-2 break-all text-xl font-semibold">{caseId ?? t("noCaseSelected")}</p>
      {isLoading ? <p className="mt-4 text-sm text-muted" role="status">{t("loadingRequestedCase")}</p> : null}
      {!isLoading && isNotFound ? (
        <p className="mt-4 text-sm text-danger" role="alert">{t("caseNotFound")}</p>
      ) : null}
      {!isLoading && error && !isNotFound ? (
        <div className="mt-4 text-sm" role="alert">
          <p className="text-danger">{t("caseCouldNotLoad")}</p>
          <button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>{t("retry")}</button>
        </div>
      ) : null}
      {!isLoading && !error ? (
        <p className="mt-4 text-sm text-muted">{t("caseNotCurrentList")}</p>
      ) : null}
    </Panel>
  );
}

function QueueStatus({ status, loginHref, onRetry, onSession }: { status: "demo" | "loading" | "live" | "error"; loginHref: string; onRetry: () => void; onSession: (trigger: HTMLElement) => void }) {
  const t = useTranslations();
  return <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-panel px-4 py-3">
    <p className="text-sm text-muted" role={status === "error" ? "alert" : "status"}>{status === "demo" ? t("demoQueue") : status === "loading" ? t("loadingLiveCases") : status === "error" ? t("liveCasesUnavailable") : t("liveQueueActive")}</p>
    {status === "error" ? <button type="button" className="text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={onRetry}>{t("retry")}</button> : null}
    {status === "demo" ? <Link className="ml-auto inline-flex min-h-9 items-center rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted hover:border-accent/60 hover:text-foreground" href={loginHref as never}>{t("signIn")}</Link> : <button type="button" className="ml-auto inline-flex min-h-9 items-center rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted hover:border-accent/60 hover:text-foreground" onClick={(event) => onSession(event.currentTarget)}>{t("sessionActive")}</button>}
  </div>;
}

function CaseNavigator({ headingRef, cases, selectedId, status, onRetry, onSelect }: { headingRef: { current: HTMLHeadingElement | null }; cases: InvestigationCase[]; selectedId?: string; status: "demo" | "loading" | "live" | "error"; onRetry: () => void; onSelect: (item: InvestigationCase) => void }) {
  const t = useTranslations();
  return <Panel as="nav" className="h-fit min-w-0 p-3 md:sticky md:top-[96px]" aria-label={t("caseNavigator")}>
    <div className="flex items-center justify-between gap-2"><h2 ref={headingRef} id="case-list-heading" tabIndex={-1} className="scroll-mt-28 text-sm font-semibold">{t("cases")}</h2><span className="text-xs text-muted">{cases.length}</span></div>
    {status === "loading" && cases.length === 0 ? <p className="mt-3 text-sm text-muted" role="status">{t("loadingCases")}</p> : null}
    {status === "error" && cases.length === 0 ? <div className="mt-3 text-sm" role="alert"><p className="text-danger">{t("casesUnavailable")}</p><button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>{t("retry")}</button></div> : null}
    {status === "error" && cases.length > 0 ? <div className="mt-3 text-sm" role="status"><p className="font-semibold text-warning">{t("refreshFailed")}</p><button type="button" className="mt-2 font-semibold text-accent" onClick={onRetry}>{t("retry")}</button></div> : null}
    {status !== "loading" && status !== "error" && cases.length === 0 ? <p className="mt-3 text-sm text-muted">{t("noCases")}</p> : null}
    <ul className="mt-3 divide-y divide-border border-t border-border">
      {cases.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={`my-1 w-full min-w-0 rounded-md border-l-[3px] px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 ${item.id === selectedId ? "border-accent bg-accent/10" : "border-transparent hover:bg-background"}`}
            aria-current={item.id === selectedId ? "true" : undefined}
            onClick={() => onSelect(item)}
          >
            <span className="block break-words text-sm font-semibold leading-5">{item.merchant}</span>
            <span className="mt-1 block break-words text-xs text-muted">{item.category}</span>
            <span className="mt-2 block break-all text-xs text-muted">{item.id}</span>
            <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="rounded-full border border-border bg-white px-2 py-0.5 font-semibold text-foreground">{statusLabel(item.status, t)}</span>
              <span className="text-muted">{item.assignee_name ?? t("unassigned")}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  </Panel>;
}

function WorkspaceToolbar({
  queueStatus,
  onRetry,
  drawer,
  loginHref,
  hasCaseContext,
  onDrawerChange
}: {
  queueStatus: "demo" | "loading" | "live" | "error";
  onRetry: () => void;
  drawer: ToolDrawer;
  loginHref: string;
  hasCaseContext: boolean;
  onDrawerChange: (drawer: ToolDrawer, trigger?: HTMLElement) => void;
}) {
  const t = useTranslations();
  const tools: Array<{ id: Exclude<ToolDrawer, null>; label: string; icon: typeof UserCheck }> = [
    { id: "session", label: queueStatus !== "demo" ? t("sessionActive") : t("signIn"), icon: UserCheck },
    ...(hasCaseContext ? [
      { id: "copilot" as const, label: t("askCopilot"), icon: MessageSquareText },
      { id: "upload" as const, label: t("uploadEvidence"), icon: FileUp }
    ] : [])
  ];

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-panel px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted" role={queueStatus === "error" ? "status" : undefined}>
          {queueStatus === "demo"
            ? t("demoQueue")
            : queueStatus === "loading"
              ? t("loadingLiveCases")
              : queueStatus === "error"
                ? t("liveCasesUnavailable")
                : t("liveQueueDecision")}
        </p>
        {queueStatus === "error" ? (
          <button type="button" className="text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={onRetry}>
            {t("retry")}
          </button>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {tools.map((tool) => {
          const Icon = tool.icon;
          const active = drawer === tool.id;
          if (tool.id === "session" && queueStatus === "demo") {
            return <Link key={tool.id} className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted transition hover:border-accent/60 hover:text-foreground" href={loginHref as never}><Icon aria-hidden className="h-4 w-4" />{tool.label}</Link>;
          }
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

function QueueStatePanel({
  workspace,
  status,
  onRetry
}: {
  workspace: "triage" | "cases";
  status: "loading" | "live" | "error";
  onRetry: () => void;
}) {
  const t = useTranslations();
  const loading = status === "loading";
  const failed = status === "error";
  const Icon = loading ? LoaderCircle : failed ? TriangleAlert : Inbox;
  const title = loading
    ? t("loadingCases")
    : failed
      ? t("casesUnavailable")
      : workspace === "triage"
        ? t("emptyTriageTitle")
        : t("emptyCasesTitle");
  const description = loading
    ? t("loadingQueueDescription")
    : failed
      ? t("emptyQueueErrorDescription")
      : workspace === "triage"
        ? t("emptyTriageDescription")
        : t("emptyCasesDescription");

  return (
    <Panel
      as="section"
      className="px-5 py-12 text-center"
      aria-labelledby={`${workspace}-queue-state-heading`}
      role={workspace === "cases" && !failed ? "status" : undefined}
      aria-live={workspace === "cases" && !failed ? "polite" : undefined}
    >
      <span className={`mx-auto flex h-14 w-14 items-center justify-center rounded-full ${failed ? "bg-danger/10 text-danger" : "bg-accent/10 text-accent"}`}>
        <Icon aria-hidden className={`h-7 w-7 ${loading ? "animate-spin" : ""}`} />
      </span>
      <h2 id={`${workspace}-queue-state-heading`} className="mt-4 text-lg font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted">{description}</p>
      {!loading ? (
        <Button type="button" variant={failed ? "primary" : "secondary"} className="mt-5" onClick={onRetry}>
          <RefreshCw aria-hidden className="h-4 w-4" />
          {failed ? t("retry") : t("refresh")}
        </Button>
      ) : null}
    </Panel>
  );
}

function AlertDetailPanel({
  caseRecord,
  canMutate,
  onDrawerChange,
  headingRef,
  onReturnToList
}: {
  caseRecord?: InvestigationCase;
  canMutate: boolean;
  onDrawerChange: (drawer: ToolDrawer, trigger?: HTMLElement) => void;
  headingRef: { current: HTMLHeadingElement | null };
  onReturnToList: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
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
    <Panel id="selected-alert-panel" as="section" className="min-w-0 p-0" aria-labelledby="selected-alert-heading">
      <div className="border-b border-border p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 ref={headingRef} id="selected-alert-heading" tabIndex={-1} className="scroll-mt-28 text-xs font-semibold uppercase tracking-wide text-muted">{t("selectedAlert")}</h2>
            <p className="mt-2 break-words text-xl font-semibold leading-tight sm:text-2xl">
              {caseRecord?.merchant ?? t("noAlertSelected")}
            </p>
            <p className="mt-2 break-all text-xs text-muted">
              <span className="font-semibold text-foreground">{t("caseId")}</span>{" "}
              <span className="select-text">{caseRecord?.id ?? "--"}</span>
            </p>
          </div>
          <Button type="button" variant="secondary" size="touch" className="shrink-0 md:hidden" onClick={onReturnToList}>
            <ArrowLeft aria-hidden className="h-4 w-4" />{t("viewCaseList")}
          </Button>
        </div>

        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-3 text-sm">
          <div><dt className="text-xs font-semibold uppercase tracking-wide text-muted">{t("status")}</dt><dd className="mt-1 inline-flex rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 font-semibold">{caseRecord ? statusLabel(caseRecord.status, t) : "--"}</dd></div>
          <div><dt className="text-xs font-semibold uppercase tracking-wide text-muted">{t("assignment")}</dt><dd className="mt-2 font-medium">{caseRecord?.assignee_name ?? t("unassigned")}</dd></div>
        </dl>
      </div>

      <div className="grid min-w-0 lg:grid-cols-[minmax(0,1.05fr)_minmax(300px,0.95fr)]">
        <div className="min-w-0 space-y-6 p-4 sm:p-5">
          <section aria-labelledby="signal-heading" className="border-l-[3px] border-accent pl-4">
            <h3 id="signal-heading" className="text-sm font-semibold">{t("whyFlagged")}</h3>
            <p className="mt-2 break-words text-lg font-semibold leading-snug">{caseRecord?.category ?? t("awaitingSelection")}</p>
            <p className="mt-2 break-words text-sm leading-6 text-muted">{caseRecord?.description ?? t("selectCaseForInvestigation")}</p>
          </section>

          <div className="space-y-6 border-t border-border pt-5">
            <section aria-labelledby="financial-context-heading">
              <h3 id="financial-context-heading" className="text-sm font-semibold">{t("financialContext")}</h3>
              <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-4 text-sm">
                <CaseFactItem label={t("exposure")} value={caseRecord ? formatAmount(caseRecord, locale) : "--"} />
                <CaseFactItem label={t("posted")} value={caseRecord?.posted_at ?? "--"} />
                <CaseFactItem label={t("detectionSource")} value={caseRecord?.source ?? "--"} />
              </dl>
            </section>

            <section aria-labelledby="supporting-documents-heading" className="border-t border-border pt-5">
              <h3 id="supporting-documents-heading" className="text-sm font-semibold">{t("supportingDocuments")}</h3>
              <p className="mt-2 text-sm leading-6 text-muted">{t("caseLinkedDocumentsUnavailable")}</p>
              <button type="button" className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={(event) => onDrawerChange("upload", event.currentTarget)}>
                {t("uploadDocument")}
              </button>
            </section>
          </div>
        </div>

        {caseRecord ? <section aria-labelledby="case-actions-heading" className="min-w-0 border-t border-border bg-background/60 p-4 sm:p-5 lg:border-l lg:border-t-0">
          <h3 id="case-actions-heading" className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted">{t("caseActions")}</h3>
          <CaseWorkflow
            key={`${caseRecord.id}:${canMutate}:${userDataEpoch}`}
            caseRecord={caseRecord}
            detail={caseDetail.data}
            canMutate={canMutate}
            isDetailLoading={caseDetail.isLoading}
            isDetailError={caseDetail.isError}
            onRetryDetail={() => void caseDetail.refetch()}
          />
        </section> : null}
      </div>
    </Panel>
  );
}

function CaseFactItem({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</dt><dd className="mt-1 break-words font-semibold">{value}</dd></div>;
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
  const t = useTranslations();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titles = {
    session: t("analystSession"),
    copilot: t("investigationCopilot"),
    upload: t("evidenceIngestion")
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
            aria-label={t("closePanel")}
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
  const t = useTranslations();
  return <div className="h-48 animate-pulse rounded-lg bg-border/50" role="status"><span className="sr-only">{t("loadingPanel")}</span></div>;
}

function statusLabel(status: InvestigationCase["status"], t: ReturnType<typeof useTranslations>) {
  return {
    new: t("statusNew"),
    needs_evidence: t("statusNeedsEvidence"),
    escalated: t("statusEscalated"),
    resolved: t("statusResolved")
  }[status];
}
