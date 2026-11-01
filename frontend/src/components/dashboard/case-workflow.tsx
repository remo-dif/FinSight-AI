"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
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

const statusLabels: Record<CaseStatus, string> = {
  new: "New",
  needs_evidence: "Needs evidence",
  escalated: "Escalated",
  resolved: "Resolved"
};

const decisionLabels: Record<CaseDecision, string> = {
  escalate: "Escalate to fraud operations",
  request_verification: "Request customer verification",
  false_positive: "Mark as false positive"
};

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
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<CaseDecision | "">("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const closed = caseRecord.status === "resolved" && (caseRecord.decision === "escalate" || caseRecord.decision === "request_verification");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Capture identity/revision as mutation variables, never from a later selection.
  type Snapshot = { caseId: string; revision: number | undefined };
  const snapshot = (): Snapshot => ({
    caseId: caseRecord.id,
    revision: detail?.id === caseRecord.id ? detail.revision : caseRecord.revision
  });
  async function refreshCase(caseId: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: caseListQueryKey() }),
      queryClient.invalidateQueries({ queryKey: caseDetailQueryKey(caseId), refetchType: "all" })
    ]);
  }
  const updateMutation = useMutation({
    mutationFn: ({ caseId, update }: Snapshot & { update: CaseUpdatePayload }) => updateCase(caseId, update),
    retry: false,
    onMutate: () => setErrorMessage(null),
    onSuccess: async (updatedCase, { caseId }) => {
      queryClient.setQueryData<CaseDetail>(caseDetailQueryKey(caseId), current =>
        current && updatedCase.id === caseId ? { ...current, ...updatedCase } : current
      );
      await refreshCase(caseId);
    },
    onError: async (error, { caseId }) => {
      setErrorMessage(error instanceof Error ? error.message : "The case update was not saved. Refresh the case and try again.");
      if (error instanceof ApiError && error.status === 409) await refreshCase(caseId);
    }
  });
  const noteMutation = useMutation({
    mutationFn: ({ caseId, content }: Snapshot & { content: string }) => addCaseNote(caseId, content),
    retry: false,
    onMutate: () => setErrorMessage(null),
    onSuccess: async (savedNote, { caseId }) => {
      queryClient.setQueryData<CaseDetail>(caseDetailQueryKey(caseId), current =>
        current ? { ...current, notes: [...current.notes, savedNote] } : current
      );
      setNote("");
      await refreshCase(caseId);
    },
    onError: async (error, { caseId }) => {
      setErrorMessage(error instanceof Error ? error.message : "The note was not saved. Please try again.");
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
        <p className="sr-only" role="status" aria-live="polite">Saving case changes.</p>
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
  return (
    <section aria-labelledby="case-state-heading">
      <h3 id="case-state-heading" className="text-sm font-semibold">Case state</h3>
      <label className="mt-3 block text-sm font-medium" htmlFor="case-status">
        Status
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
        <p className="text-sm text-muted">Assigned to {caseRecord.assignee_name ?? "No analyst"}</p>
        <button
          type="button"
          className="h-9 rounded-md border border-border bg-white px-3 text-sm font-semibold text-foreground hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canMutate || updatePending}
          onClick={() => onUpdate({ assignee: caseRecord.assigned_to_me ? "unassigned" : "me" })}
        >
          {caseRecord.assigned_to_me ? "Unassign me" : "Assign to me"}
        </button>
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
  return (
    <section aria-labelledby="case-decision-heading">
      <h3 id="case-decision-heading" className="text-sm font-semibold">Investigation decision</h3>
      {caseRecord.decision ? (
        <div className="mt-3 rounded-md border border-border bg-background p-3">
          <p className="text-sm font-semibold">{decisionLabels[caseRecord.decision]}</p>
          <p className="mt-1 text-sm leading-5 text-muted">{caseRecord.decision_reason}</p>
        </div>
      ) : caseRecord.status === "resolved" ? (
        <p className="mt-3 text-sm text-muted">This case is resolved. Further status changes and decisions are unavailable.</p>
      ) : (
        <form className="mt-3 space-y-3" onSubmit={onSubmit}>
          <label className="block text-sm font-medium" htmlFor="case-decision">
            Decision
            <select
              id="case-decision"
              className="mt-1 h-10 w-full rounded-md border border-border bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              value={decision}
              onChange={(event) => onDecisionChange(event.target.value as CaseDecision | "")}
              disabled={!canMutate || updatePending}
              required
            >
              <option value="">Select a decision</option>
              {Object.entries(decisionLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium" htmlFor="case-decision-reason">
            Reason
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
          <button
            type="submit"
            className="h-10 rounded-md bg-accent px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!canMutate || updatePending || !decision || !reason.trim()}
            aria-busy={updatePending}
          >
            {updatePending ? "Recording..." : "Record decision"}
          </button>
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
  return (
    <section aria-labelledby="case-notes-heading">
      <h3 id="case-notes-heading" className="text-sm font-semibold">Analyst notes</h3>
      {isDetailLoading ? <p className="mt-2 text-sm text-muted" role="status">Loading case notes...</p> : null}
      {isDetailError ? (
        <div className="mt-2 flex items-center gap-3 text-sm" role="alert">
          <p className="text-danger">Case notes could not be loaded.</p>
          <button type="button" className="font-semibold text-accent underline-offset-4 hover:underline" onClick={onRetryDetail}>
            Retry
          </button>
        </div>
      ) : null}
      {!canMutate ? <p className="mt-2 text-sm text-muted">{isClosed ? "Notes are read-only after closure." : "Sign in to add notes or record case actions."}</p> : null}
      {detail?.notes.length ? (
        <ol className="mt-3 space-y-2">
          {detail.notes.map((item) => (
            <li key={item.id} className="rounded-md border border-border bg-background p-3">
              <p className="text-xs font-semibold text-muted">
                {item.author_name}{" - "}<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-5">{item.content}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {canMutate ? (
        <form className="mt-3 space-y-2" onSubmit={onSubmit}>
          <label className="block text-sm font-medium" htmlFor="case-note-content">Add a note</label>
          <textarea
            id="case-note-content"
            className="min-h-20 w-full rounded-md border border-border bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
            maxLength={4000}
            disabled={notePending}
            required
          />
          <button
            type="submit"
            className="h-9 rounded-md border border-border bg-white px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
            disabled={notePending || !note.trim()}
            aria-busy={notePending}
          >
            {notePending ? "Saving note..." : "Add note"}
          </button>
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
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const closed = caseRecord.status === "resolved";
  const hasOutcome = Boolean(detail?.follow_ups?.length);
  const mutation = useMutation({
    mutationFn: async ({ caseId, revision, content, close, decision }: {
      caseId: string; revision: number; content: string; close: boolean; decision: CaseDecision | null;
    }) => {
      const payload = { reason: content, expected_revision: revision };
      if (close) return closeCase(caseId, payload);
      const action = decision === "escalate" ? "escalation_outcome" : "verification_outcome";
      return recordCaseFollowUp(caseId, { ...payload, action });
    },
    retry: false,
    onMutate: () => setError(null),
    onSuccess: () => setReason(""),
    onError: (failure) => setError(failure instanceof Error ? failure.message : "The case action was not saved."),
    onSettled: async (_data, _error, { caseId }) => {
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
      <h3 id="case-follow-up-heading" className="text-sm font-semibold">Follow-up investigation</h3>
      {detail?.follow_ups?.length ? (
        <ol className="space-y-2">
          {detail.follow_ups.map((item) => (
            <li key={item.id} className="rounded-md border border-border p-3">
              <p className="text-sm font-semibold">{item.action === "close" ? "Case closed" : "Investigation outcome recorded"}</p>
              <p className="whitespace-pre-wrap text-sm">{item.reason}</p>
              <p className="text-xs text-muted">{item.previous_status}{" to "}{item.resulting_status}{" - "}<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></p>
            </li>
          ))}
        </ol>
      ) : null}
      {closed ? <p className="text-sm text-muted">This case is closed. Its decision and history are preserved.</p> : (
        <form className="space-y-2" onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim() && !disabled && detail?.revision !== undefined) mutation.mutate({
            caseId: caseRecord.id, revision: detail.revision, content: reason.trim(), close: hasOutcome, decision: caseRecord.decision
          });
        }}>
          <label className="block text-sm" htmlFor="case-follow-up-reason">
            {hasOutcome ? "Closure reason" : caseRecord.decision === "request_verification" ? "Verification result and outcome" : "Escalation investigation outcome"}
          </label>
          <textarea id="case-follow-up-reason" className="w-full rounded-md border border-border p-2" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} required disabled={disabled} />
          <button type="submit" className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white disabled:opacity-60" disabled={disabled || !reason.trim()}>
            {hasOutcome ? "Close investigation" : "Record follow-up outcome"}
          </button>
        </form>
      )}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}
