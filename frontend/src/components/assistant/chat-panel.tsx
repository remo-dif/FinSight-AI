"use client";

import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { LoaderCircle, Send, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import {
  DocumentCitation,
  fetchUploadedDocuments,
  sendChatMessage,
  uploadedDocumentsQueryKey
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/store/session";

type Message = {
  role: "user" | "assistant";
  content: string;
  review?: string;
  tone?: "default" | "error";
  status?: "ok" | "abstained" | "provider_error" | "insufficient_evidence" | "extractive_preview";
  citations?: DocumentCitation[];
  sources?: DocumentCitation[];
};

const statusLabels: Record<NonNullable<Message["status"]>, string> = {
  ok: "References validated; claim-level support is not verified.",
  abstained: "The assistant abstained because it could not validate enough evidence.",
  provider_error: "Document Q&A provider error.",
  insufficient_evidence: "No sufficiently relevant document evidence was found.",
  extractive_preview: "Extractive preview; not a generated answer."
};
const DOCUMENT_PAGE_SIZE = 100;
const MAX_DOCUMENT_SELECTION = 100;

export function ChatPanel() {
  const statusId = useId();
  const documentsId = useId();
  const chatSessionId = useSessionStore((state) => state.chatSessionId);
  const token = useSessionStore((state) => state.accessToken);
  const setChatSessionId = useSessionStore((state) => state.setChatSessionId);
  const [input, setInput] = useState("Show my monthly summary");
  const [mode, setMode] = useState<"finance" | "document_qa">("finance");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectionError, setSelectionError] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Ask about monthly cash flow, category spending, top merchants, unusual transactions, recurring charges, or estimated budgets. Answers are checked against your transaction data."
    }
  ]);
  const documents = useInfiniteQuery({
    queryKey: uploadedDocumentsQueryKey,
    queryFn: ({ pageParam }) => fetchUploadedDocuments(pageParam, DOCUMENT_PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === DOCUMENT_PAGE_SIZE ? pages.length * DOCUMENT_PAGE_SIZE : undefined,
    enabled: mode === "document_qa" && Boolean(token),
    retry: false
  });
  useEffect(() => {
    setSelectedDocumentIds([]);
    setSelectionError("");
  }, [token]);

  const chat = useMutation({
    mutationFn: sendChatMessage,
    onSuccess: (data, variables) => {
      if (variables.mode === "finance") setChatSessionId(data.session_id);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          review: data.grounding_note ?? data.review,
          status: variables.mode === "document_qa" ? data.status : undefined,
          citations: data.citations,
          sources: data.sources
        }
      ]);
    },
    onError: (error) => {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content:
            error instanceof Error
              ? error.message
              : "The assistant could not complete that request. Please try again.",
          tone: "error"
        }
      ]);
    }
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || chat.isPending || (mode === "document_qa" && selectedDocumentIds.length === 0)) return;
    setMessages((current) => [...current, { role: "user", content: text }]);
    chat.mutate({
      message: text,
      sessionId: mode === "finance" ? chatSessionId : null,
      mode,
      ...(mode === "document_qa" ? { documentIds: selectedDocumentIds } : {})
    });
    setInput("");
  }

  const indexedDocuments = token
    ? documents.data?.pages.flat().filter((document) => document.status === "indexed") ?? []
    : [];

  return (
    <Panel as="section" className="flex h-[520px] flex-col p-4" aria-labelledby="assistant-heading">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div>
          <h2 id="assistant-heading" className="text-base font-semibold">Investigation copilot</h2>
          <p className="mt-1 text-sm leading-5 text-muted">
            {mode === "finance" ? "Tool-grounded financial analysis" : "Ask questions about your uploaded documents"}
          </p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-success/10 text-success">
          <ShieldCheck aria-hidden className="h-5 w-5" />
        </span>
      </div>

      <div className="mt-3 flex gap-2" role="group" aria-label="Assistant mode">
        <button
          type="button"
          className={modeButtonClass(mode === "finance")}
          aria-pressed={mode === "finance"}
          onClick={() => setMode("finance")}
        >
          Finance
        </button>
        <button
          type="button"
          className={modeButtonClass(mode === "document_qa")}
          aria-pressed={mode === "document_qa"}
          onClick={() => setMode("document_qa")}
        >
          Document Q&amp;A
        </button>
      </div>

      {mode === "document_qa" ? (
        <div className="mt-3">
          <label htmlFor={documentsId} className="block text-xs font-semibold">
            Select indexed documents
          </label>
          {!token ? (
            <p className="mt-1 text-xs text-muted" role="status">Sign in to select your uploaded documents.</p>
          ) : documents.isPending ? (
            <p className="mt-1 text-xs text-muted" role="status">Loading your authorized documents...</p>
          ) : documents.isError ? (
            <p className="mt-1 text-xs text-danger" role="alert">{documents.error.message}</p>
          ) : indexedDocuments.length === 0 ? (
            <p className="mt-1 text-xs text-muted" role="status">No indexed documents are available for Q&amp;A.</p>
          ) : (
            <select
              id={documentsId}
              multiple
              value={selectedDocumentIds}
              onChange={(event) => {
                const nextSelection = Array.from(
                  event.currentTarget.selectedOptions,
                  (option) => option.value
                );
                if (nextSelection.length > MAX_DOCUMENT_SELECTION) {
                  setSelectionError(`Select no more than ${MAX_DOCUMENT_SELECTION} documents.`);
                  return;
                }
                setSelectedDocumentIds(nextSelection);
                setSelectionError("");
              }}
              className="mt-1 min-h-16 w-full rounded-md border border-border bg-white px-2 py-1 text-xs"
              aria-describedby={`${documentsId}-hint`}
            >
              {indexedDocuments.map((document) => (
                <option key={document.id} value={document.id}>{document.filename}</option>
              ))}
            </select>
          )}
          {indexedDocuments.length > 0 ? (
            <p id={`${documentsId}-hint`} className="mt-1 text-xs text-muted">
              Choose up to 100 indexed documents. Only documents owned by your account can be queried.
            </p>
          ) : null}
          {selectionError ? <p className="mt-1 text-xs text-danger" role="alert">{selectionError}</p> : null}
          {documents.hasNextPage ? (
            <Button
              type="button"
              className="mt-2 h-8 border border-border bg-white px-3 text-xs text-muted hover:border-accent/60 hover:text-foreground"
              onClick={() => void documents.fetchNextPage()}
              disabled={documents.isFetchingNextPage}
            >
              {documents.isFetchingNextPage ? "Loading documents..." : "Load more documents"}
            </Button>
          ) : null}
          {documents.isFetchNextPageError ? (
            <p className="mt-1 text-xs text-danger" role="alert">
              {documents.error.message}
            </p>
          ) : null}
        </div>
      ) : null}

      <div
        className="flex-1 space-y-3 overflow-y-auto py-4 pr-1"
        role="log"
        aria-live="polite"
        aria-label="Conversation messages"
      >
        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            role={message.tone === "error" ? "alert" : undefined}
            className={cn(
              "max-w-[85%] rounded-lg p-3 text-sm leading-6",
              message.role === "user"
                ? "ml-auto bg-accent text-white shadow-sm"
                : "border border-border bg-background",
              message.tone === "error" && "border-danger/40 bg-danger/5 text-danger"
            )}
          >
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.status ? (
              <p className="mt-2 text-xs font-medium text-muted" role="status">
                {statusLabels[message.status]}
              </p>
            ) : null}
            {message.review ? (
              <p className="mt-2 border-t border-border pt-2 text-xs leading-5 text-muted">
                {message.review}
              </p>
            ) : null}
            {message.citations?.length ? (
              <CitationList title="Cited references" citations={message.citations} />
            ) : null}
            {message.sources?.length ? (
              <CitationList title="Retrieved sources (not all necessarily cited)" citations={message.sources} />
            ) : null}
          </div>
        ))}
        {chat.isPending ? (
          <div className="flex max-w-[85%] items-center gap-2 rounded-lg border border-border bg-background p-3 text-sm leading-6 text-muted" role="status">
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin text-accent" />
            {mode === "document_qa" ? "Searching authorized documents..." : "Asking the investigation tools..."}
          </div>
        ) : null}
      </div>
      <p id={statusId} className="sr-only" aria-live="assertive">
        {chat.isPending ? "The assistant is preparing an answer." : chat.isError ? "The last assistant request failed." : ""}
      </p>
      <form className="flex gap-2 border-t border-border pt-4" onSubmit={submit} aria-label="Send a message to the finance assistant">
        <input
          aria-label={mode === "document_qa" ? "Ask about selected documents" : "Ask the finance assistant"}
          aria-describedby={statusId}
          className="min-w-0 flex-1 rounded-md border border-border bg-white px-3 text-sm outline-none transition placeholder:text-muted/70 hover:border-accent/70 focus:border-accent focus:ring-2 focus:ring-accent/30"
          placeholder={mode === "document_qa" ? "Ask about the selected documents" : "Ask about cash flow, merchants, or spending"}
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <Button
          type="submit"
          aria-label="Send message"
          className="h-10 w-10 px-0"
          disabled={
            !input.trim()
            || chat.isPending
            || (mode === "document_qa" && (!token || selectedDocumentIds.length === 0))
          }
        >
          {chat.isPending ? (
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Send aria-hidden className="h-4 w-4" />
          )}
        </Button>
      </form>
    </Panel>
  );
}

function CitationList({ title, citations }: { title: string; citations: DocumentCitation[] }) {
  return (
    <section className="mt-2 border-t border-border pt-2">
      <h3 className="text-xs font-semibold">{title}</h3>
      <ul className="mt-1 space-y-2">
        {citations.map((citation) => (
          <li key={citation.reference} className="rounded border border-border bg-white p-2 text-xs leading-5">
            <p className="font-medium">{citation.document_name} · chunk {citation.chunk_index ?? "unknown"}</p>
            <p className="mt-1 whitespace-pre-wrap text-muted">{citation.excerpt}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function modeButtonClass(active: boolean) {
  return cn(
    "min-h-8 rounded-md border px-3 text-xs font-semibold transition",
    active
      ? "border-accent bg-accent/10 text-accent"
      : "border-border bg-white text-muted hover:border-accent/60 hover:text-foreground"
  );
}
