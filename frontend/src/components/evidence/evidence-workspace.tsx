"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { FileText, RefreshCw } from "lucide-react";
import { ChatPanel } from "@/components/assistant/chat-panel";
import { AuthPanel } from "@/components/auth/auth-panel";
import { Panel } from "@/components/ui/panel";
import { UploadPanel } from "@/components/uploads/upload-panel";
import { fetchUploadedDocuments, uploadedDocumentsQueryKey } from "@/lib/api";
import { useSessionStore } from "@/store/session";

const PAGE_SIZE = 100;

export function EvidenceWorkspace() {
  const token = useSessionStore((state) => state.accessToken);
  const documents = useInfiniteQuery({
    queryKey: uploadedDocumentsQueryKey,
    queryFn: ({ pageParam }) => fetchUploadedDocuments(pageParam, PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined,
    enabled: Boolean(token),
    retry: false
  });
  const items = documents.data?.pages.flat() ?? [];

  if (!token) {
    return <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Panel as="section" className="p-6" aria-labelledby="document-library-heading">
        <h2 id="document-library-heading" className="text-lg font-semibold">Document Library</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Sign in to view and upload documents. Demo records are not shown because document access is user-specific.</p>
      </Panel>
      <AuthPanel />
    </div>;
  }

  return <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
    <div className="space-y-4">
      <Panel as="section" className="p-4" aria-labelledby="document-library-heading">
        <div className="flex items-start justify-between gap-3">
          <div><h2 id="document-library-heading" className="text-lg font-semibold">Document Library</h2><p className="mt-1 text-sm text-muted">Documents available to your authenticated account.</p></div>
          <button type="button" className="inline-flex min-h-9 items-center gap-2 rounded-md border border-border bg-white px-3 text-sm font-semibold text-muted hover:border-accent/60 hover:text-foreground disabled:opacity-60" onClick={() => void documents.refetch()} disabled={documents.isFetching}>
            <RefreshCw aria-hidden className={`h-4 w-4 ${documents.isFetching ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        {documents.isPending ? <p className="mt-6 text-sm text-muted" role="status">Loading documents...</p> : null}
        {documents.isError ? <div className="mt-6" role="alert"><p className="text-sm font-medium text-danger">The document library could not be loaded.</p><button type="button" className="mt-2 text-sm font-semibold text-accent underline-offset-4 hover:underline" onClick={() => void documents.refetch()}>Retry</button></div> : null}
        {!documents.isPending && !documents.isError && items.length === 0 ? <p className="mt-6 rounded-md border border-dashed border-border p-5 text-sm text-muted">No documents have been uploaded yet.</p> : null}
        {items.length > 0 ? <ul className="mt-4 divide-y divide-border" aria-label="Documents">{items.map((document) => <li key={document.id} className="flex items-center gap-3 py-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent"><FileText aria-hidden className="h-4 w-4" /></span>
          <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{document.filename}</p><p className="mt-1 text-xs text-muted"><span className="capitalize">{document.status}</span>{" · "}<time dateTime={document.created_at}>{new Date(document.created_at).toLocaleString()}</time></p></div>
        </li>)}</ul> : null}
        {documents.hasNextPage ? <button type="button" className="mt-4 min-h-9 rounded-md border border-border bg-white px-3 text-sm font-semibold" onClick={() => void documents.fetchNextPage()} disabled={documents.isFetchingNextPage}>{documents.isFetchingNextPage ? "Loading..." : "Load more"}</button> : null}
      </Panel>
      <UploadPanel />
    </div>
    <ChatPanel initialMode="document_qa" />
  </div>;
}
