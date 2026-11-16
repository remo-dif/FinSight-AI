"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useSessionStore } from "@/store/session";
import { Button } from "@/components/ui/button";
import { useLocale, useTranslations } from "@/i18n/context";
import {
  ApiError,
  addCaseNote,
  recordCaseFollowUp,
  closeCase,
  CaseDecision,
  CaseDetail,
  CaseStatus,
  caseDetailQueryKey,
  caseListQueryKey,
  InvestigationCase,
  updateCase
} from "@/lib/api";

type CaseUpdatePayload = Parameters<typeof updateCase>[1];

export function CaseWorkflow({
  caseRecord,
  detail,
  canMutate,
  isDetailLoading,
  isDetailError,
  onRetryDetail
}: {
  caseRecord: InvestigationCase;
  detail?: CaseDetail;
  canMutate: boolean;
  isDetailLoading: boolean;
  isDetailError: boolean;
  onRetryDetail: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
  const [decision, setDecision] = useState<CaseDecision | "">("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const closed = caseRecord.status === "resolved" && (caseRecord.decision === "escalate" || caseRecord.decision === "request_verification");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Capture identity/revision as mutation variables, never from a later selection.
  type Snapshot = { caseId: string; revision: number | undefined; userDataEpoch: number };
  const snapshot = (): Snapshot => ({
    caseId: caseRecord.id,
    userDataEpoch,
    revision: detail?.id === caseRecord.id ? detail.revision : caseRecord.revision
  });
  async function refreshCase(caseId: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: caseListQueryKey() }),
      queryClient.invalidateQueries({ queryKey: caseDetailQueryKey(caseId), refetchType: "all" })
    ]);
  }
  const updateMutation = useMutation({
    mutationFn: ({ caseId, update, userDataEpoch }: Snapshot & { update: CaseUpdatePayload }) => updateCase(caseId, update, userDataEpoch),
    retry: false,
    onMutate: () => setErrorMessage(null),
    onSuccess: async (updatedCase, { caseId, userDataEpoch }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      queryClient.setQueryData<CaseDetail>(caseDetailQueryKey(caseId), current =>
        current && updatedCase.id === caseId ? { ...current, ...updatedCase } : current
      );
      await refreshCase(caseId);
    },
    onError: async (error, { caseId, userDataEpoch }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      setErrorMessage(error instanceof Error ? error.message : t("caseUpdateError"));
      if (error instanceof ApiError && error.status === 409) await refreshCase(caseId);
    }
  });
  const noteMutation = useMutation({
    mutationFn: ({ caseId, content, userDataEpoch }: Snapshot & { content: string }) => addCaseNote(caseId, content, userDataEpoch),
    retry: false,
    onMutate: () => setErrorMessage(null),
    onSuccess: async (savedNote, { caseId, userDataEpoch }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      queryClient.setQueryData<CaseDetail>(caseDetailQueryKey(caseId), current =>
        current ? { ...current, notes: [...current.notes, savedNote] } : current
      );
      setNote("");
      await refreshCase(caseId);
    },
    onError: async (error, { caseId, userDataEpoch }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      setErrorMessage(error instanceof Error ? error.message : t("noteUpdateError"));
      if (error instanceof ApiError && error.status === 409) await refreshCase(caseId);
    }
  });

  function recordDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!decision || !reason.trim() || updateMutation.isPending) return;
    updateMutation.mutate({ ...snapshot(), update: { decision, reason: reason.trim() } });
  }
  function recordNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!note.trim() || noteMutation.isPending) return;
    noteMutation.mutate({ ...snapshot(), content: note.trim() });
  }

  const updatePending = updateMutation.isPending;

  return (
    <div className="space-y-5">
      <CaseStateControls
        caseRecord={caseRecord}
        canMutate={canMutate && !closed}
        updatePending={updatePending}
        onUpdate={(update) => updateMutation.mutate({ ...snapshot(), update })}
      />

      <CaseDecisionSection
        caseRecord={caseRecord}
        canMutate={canMutate && !closed}
        updatePending={updatePending}
        decision={decision}
        reason={reason}
        onDecisionChange={setDecision}
        onReasonChange={setReason}
        onSubmit={recordDecision}
      />

      <CaseFollowUpSection key={caseRecord.id} caseRecord={caseRecord} detail={detail} canMutate={canMutate} blocked={updatePending || noteMutation.isPending || isDetailLoading || isDetailError} />

      <CaseNotesSection
        isClosed={closed}
        detail={detail}
        canMutate={canMutate && !closed}
        isDetailLoading={isDetailLoading}
        isDetailError={isDetailError}
        onRetryDetail={onRetryDetail}
        note={note}
        notePending={noteMutation.isPending}
        onNoteChange={setNote}
        onSubmit={recordNote}
      />

      {errorMessage ? <p className="text-sm text-danger" role="alert">{errorMessage}</p> : null}
      {updatePending || noteMutation.isPending ? (
        <p className="sr-only" role="status" aria-live="polite">{t("savingChanges")}</p>
      ) : null}
    </div>
  );
}

function CaseStateControls({
  caseRecord,
  canMutate,
  updatePending,
  onUpdate
}: {
  caseRecord: InvestigationCase;
  canMutate: boolean;
  updatePending: boolean;
  onUpdate: (update: CaseUpdatePayload) => void;
}) {
  const t = useTranslations();
  const statusLabels: Record<CaseStatus, string> = {
    new: t("statusNew"),
    needs_evidence: t("statusNeedsEvidence"),
    escalated: t("statusEscalated"),
    resolved: t("statusResolved")
  };
  return (
    <section aria-labelledby="case-state-heading">
      <h3 id="case-state-heading" className="text-sm font-semibold">{t("caseState")}</h3>
      <label className="mt-3 block text-sm font-medium" htmlFor="case-status">
        {t("status")}
        <select
          id="case-status"
          className="mt-1 h-10 w-full rounded-md border border-border bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          value={caseRecord.status}
          disabled={!canMutate || updatePending || Boolean(caseRecord.decision) || caseRecord.status === "resolved"}
          onChange={(event) => onUpdate({ status: event.target.value as CaseStatus })}
        >
          {Object.entries(statusLabels).map(([value, label]) => (
            <option key={value} value={value} disabled={value === "resolved" || (value === "new" && caseRecord.status !== "new")}>{label}</option>
          ))}
        </select>
      </label>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">{t("assignedTo", { name: caseRecord.assignee_name ?? t("noAnalyst") })}</p>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={!canMutate || updatePending}
          onClick={() => onUpdate({ assignee: caseRecord.assigned_to_me ? "unassigned" : "me" })}
        >
          {caseRecord.assigned_to_me ? t("unassignMe") : t("assignToMe")}
        </Button>
      </div>
    </section>
  );
}

function CaseDecisionSection({
  caseRecord,
  canMutate,
  updatePending,
  decision,
  reason,
  onDecisionChange,
  onReasonChange,
  onSubmit
}: {
  caseRecord: InvestigationCase;
  canMutate: boolean;
  updatePending: boolean;
  decision: CaseDecision | "";
  reason: string;
  onDecisionChange: (decision: CaseDecision | "") => void;
  onReasonChange: (reason: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const t = useTranslations();
  const decisionLabels: Record<CaseDecision, string> = {
    escalate: t("escalateDecision"),
    request_verification: t("verificationDecision"),
    false_positive: t("falsePositiveDecision")
  };
  return (
    <section aria-labelledby="case-decision-heading">
      <h3 id="case-decision-heading" className="text-sm font-semibold">{t("investigationDecision")}</h3>
      {caseRecord.decision ? (
        <div className="mt-3 rounded-md border border-border bg-background p-3">
          <p className="text-sm font-semibold">{decisionLabels[caseRecord.decision]}</p>
          <p className="mt-1 text-sm leading-5 text-muted">{caseRecord.decision_reason}</p>
        </div>
      ) : caseRecord.status === "resolved" ? (
        <p className="mt-3 text-sm text-muted">{t("resolvedCase")}</p>
      ) : (
        <form className="mt-3 space-y-3" onSubmit={onSubmit}>
          <label className="block text-sm font-medium" htmlFor="case-decision">
            {t("decision")}
            <select
              id="case-decision"
              className="mt-1 h-10 w-full rounded-md border border-border bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              value={decision}
              onChange={(event) => onDecisionChange(event.target.value as CaseDecision | "")}
              disabled={!canMutate || updatePending}
              required
            >
              <option value="">{t("selectDecision")}</option>
              {Object.entries(decisionLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium" htmlFor="case-decision-reason">
            {t("reason")}
            <textarea
              id="case-decision-reason"
              className="mt-1 min-h-20 w-full rounded-md border border-border bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              maxLength={500}
              disabled={!canMutate || updatePending}
              required
            />
          </label>
          <Button
            type="submit"
            disabled={!canMutate || updatePending || !decision || !reason.trim()}
            aria-busy={updatePending}
          >
            {updatePending ? t("recording") : t("recordDecision")}
          </Button>
        </form>
      )}
    </section>
  );
}

function CaseNotesSection({
  isClosed = false,
  detail,
  canMutate,
  isDetailLoading,
  isDetailError,
  onRetryDetail,
  note,
  notePending,
  onNoteChange,
  onSubmit
}: {
  detail?: CaseDetail;
  canMutate: boolean;
  isDetailLoading: boolean;
  isDetailError: boolean;
  onRetryDetail: () => void;
  note: string;
  notePending: boolean;
  onNoteChange: (note: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isClosed?: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  return (
    <section aria-labelledby="case-notes-heading">
      <h3 id="case-notes-heading" className="text-sm font-semibold">{t("analystNotes")}</h3>
      {isDetailLoading ? <p className="mt-2 text-sm text-muted" role="status">{t("loadingCaseNotes")}</p> : null}
      {isDetailError ? (
        <div className="mt-2 flex items-center gap-3 text-sm" role="alert">
          <p className="text-danger">{t("caseNotesError")}</p>
          <Button type="button" variant="text" onClick={onRetryDetail}>
            {t("retry")}
          </Button>
        </div>
      ) : null}
      {!canMutate ? <p className="mt-2 text-sm text-muted">{isClosed ? t("notesReadOnly") : t("signInForCaseActions")}</p> : null}
      {detail?.notes.length ? (
        <ol className="mt-3 space-y-2">
          {detail.notes.map((item) => (
            <li key={item.id} className="rounded-md border border-border bg-background p-3">
              <p className="text-xs font-semibold text-muted">
                {item.author_name}{" - "}<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-5">{item.content}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {canMutate ? (
        <form className="mt-3 space-y-2" onSubmit={onSubmit}>
          <label className="block text-sm font-medium" htmlFor="case-note-content">{t("addNote")}</label>
          <textarea
            id="case-note-content"
            className="min-h-20 w-full rounded-md border border-border bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
            maxLength={4000}
            disabled={notePending}
            required
          />
          <Button
            type="submit"
            variant="secondary"
            size="sm"
            disabled={notePending || !note.trim()}
            aria-busy={notePending}
          >
            {notePending ? t("savingNote") : t("saveNote")}
          </Button>
        </form>
      ) : null}
    </section>
  );
}


function CaseFollowUpSection({ caseRecord, detail, canMutate, blocked }: {
  caseRecord: InvestigationCase;
  detail?: CaseDetail;
  canMutate: boolean;
  blocked: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const closed = caseRecord.status === "resolved";
  const hasOutcome = Boolean(detail?.follow_ups?.length);
  const mutation = useMutation({
    mutationFn: async ({ caseId, revision, content, close, decision, userDataEpoch }: {
      caseId: string; revision: number; content: string; close: boolean; decision: CaseDecision | null; userDataEpoch: number;
    }) => {
      const payload = { reason: content, expected_revision: revision };
      if (close) return closeCase(caseId, payload, userDataEpoch);
      const action = decision === "escalate" ? "escalation_outcome" : "verification_outcome";
      return recordCaseFollowUp(caseId, { ...payload, action }, userDataEpoch);
    },
    retry: false,
    onMutate: () => setError(null),
    onSuccess: () => setReason(""),
    onError: (failure) => setError(failure instanceof Error ? failure.message : t("caseActionError")),
    onSettled: async (_data, _error, { caseId, userDataEpoch }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: caseListQueryKey() }),
        queryClient.invalidateQueries({ queryKey: caseDetailQueryKey(caseId), refetchType: "all" })
      ]);
    }
  });
  if (caseRecord.decision !== "escalate" && caseRecord.decision !== "request_verification") return null;
  const disabled = !canMutate || blocked || mutation.isPending || detail?.id !== caseRecord.id || detail?.revision === undefined;
  return (
    <section aria-labelledby="case-follow-up-heading" className="space-y-3">
      <h3 id="case-follow-up-heading" className="text-sm font-semibold">{t("followUpInvestigation")}</h3>
      {detail?.follow_ups?.length ? (
        <ol className="space-y-2">
          {detail.follow_ups.map((item) => (
            <li key={item.id} className="rounded-md border border-border p-3">
              <p className="text-sm font-semibold">{item.action === "close" ? t("caseClosed") : t("outcomeRecorded")}</p>
              <p className="whitespace-pre-wrap text-sm">{item.reason}</p>
              <p className="text-xs text-muted">{t("statusTransition", { previous: localizedStatus(item.previous_status, t), resulting: localizedStatus(item.resulting_status, t) })}{" - "}<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time></p>
            </li>
          ))}
        </ol>
      ) : null}
      {closed ? <p className="text-sm text-muted">{t("closedCase")}</p> : (
        <form className="space-y-2" onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim() && !disabled && detail?.revision !== undefined) mutation.mutate({
            caseId: caseRecord.id, userDataEpoch, revision: detail.revision, content: reason.trim(), close: hasOutcome, decision: caseRecord.decision
          });
        }}>
          <label className="block text-sm" htmlFor="case-follow-up-reason">
            {hasOutcome ? t("closureReason") : caseRecord.decision === "request_verification" ? t("verificationOutcome") : t("escalationOutcome")}
          </label>
          <textarea id="case-follow-up-reason" className="w-full rounded-md border border-border p-2" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} required disabled={disabled} />
          <button type="submit" className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white disabled:opacity-60" disabled={disabled || !reason.trim()}>
            {hasOutcome ? t("closeInvestigation") : t("recordFollowUp")}
          </button>
        </form>
      )}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}

function localizedStatus(status: CaseStatus, t: ReturnType<typeof useTranslations>) {
  return {
    new: t("statusNew"),
    needs_evidence: t("statusNeedsEvidence"),
    escalated: t("statusEscalated"),
    resolved: t("statusResolved")
  }[status];
}
