"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  caseDetailQueryKey,
  caseListQueryKey,
  fetchCaseDocuments,
  fetchUploadedDocuments,
  linkCaseDocument,
  unlinkCaseDocument
} from "@/lib/api";
import { useTranslations } from "@/i18n/context";
import { useSessionStore } from "@/store/session";

const PAGE_SIZE = 100;

export function CaseDocuments({ caseId, canMutate, isClosed }: { caseId: string; canMutate: boolean; isClosed: boolean }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const documentsKey = ["case-documents", caseId, userDataEpoch] as const;
  const documents = useQuery({
    queryKey: documentsKey,
    queryFn: () => fetchCaseDocuments(caseId, userDataEpoch),
    enabled: canMutate,
    retry: false
  });
  const uploads = useInfiniteQuery({
    queryKey: ["case-document-choices", userDataEpoch],
    queryFn: ({ pageParam }) => fetchUploadedDocuments(pageParam, PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined,
    enabled: canMutate && !isClosed,
    retry: false
  });
  const mutation = useMutation({
    mutationFn: async ({ fileId, action }: { fileId: string; action: "link" | "unlink" }) => {
      if (action === "link") await linkCaseDocument(caseId, fileId, userDataEpoch);
      else await unlinkCaseDocument(caseId, fileId, userDataEpoch);
    },
    retry: false,
    onMutate: () => { setError(null); setMessage(null); },
    onSuccess: async (_result, { action }) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      setSelectedFileId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: documentsKey }),
        queryClient.invalidateQueries({ queryKey: caseDetailQueryKey(caseId) }),
        queryClient.invalidateQueries({ queryKey: caseListQueryKey() })
      ]);
      setMessage(action === "link" ? t("caseDocumentLinked") : t("caseDocumentRemoved"));
    },
    onError: (cause) => {
      if (useSessionStore.getState().userDataEpoch !== userDataEpoch) return;
      setError(cause instanceof ApiError && cause.status === 409 ? t("caseDocumentConflict") : t("caseDocumentActionError"));
    }
  });
  const linkedIds = new Set(documents.data?.map((item) => item.id) ?? []);
  const choices = uploads.data?.pages.flat().filter((item) => !linkedIds.has(item.id)) ?? [];

  if (!canMutate) return <p className="mt-2 text-sm text-muted">{t("signInForCaseDocuments")}</p>;

  return <div className="mt-3 space-y-3 text-sm">
    {documents.isPending ? <p role="status" className="text-muted">{t("loadingCaseDocuments")}</p> : null}
    {documents.isError ? <div role="alert" className="flex flex-wrap items-center gap-2 text-danger">
      <span>{t("caseDocumentsError")}</span>
      <Button type="button" variant="text" onClick={() => void documents.refetch()}>{t("retry")}</Button>
    </div> : null}
    {documents.isSuccess && documents.data.length === 0 ? <p className="text-muted">{t("noCaseDocuments")}</p> : null}
    {documents.isSuccess && documents.data.length > 0 ? <ul className="space-y-2" aria-label={t("linkedCaseDocuments")}>
      {documents.data.map((item) => <li key={item.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background p-3">
        <div className="min-w-0">
          <p className="break-words font-medium">{item.filename}</p>
          <p className="text-xs text-muted">{item.status === "indexed" ? t("documentStatusIndexed") : item.status === "processed" ? t("documentStatusProcessed") : item.status === "uploaded" ? t("documentStatusUploaded") : item.status} · {t("linkedBy", { name: item.linked_by_name })}</p>
        </div>
        {!isClosed ? <Button type="button" variant="secondary" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate({ fileId: item.id, action: "unlink" })} aria-label={t("removeCaseDocument", { name: item.filename })}>{t("remove")}</Button> : null}
      </li>)}
    </ul> : null}
    {isClosed ? <p className="text-muted">{t("caseDocumentsReadOnly")}</p> : <div className="space-y-2">
      <label className="block font-medium" htmlFor="case-document-choice">{t("chooseCaseDocument")}</label>
      <select id="case-document-choice" className="min-h-11 w-full rounded-md border border-border bg-white px-3" value={selectedFileId} disabled={uploads.isPending || uploads.isError || mutation.isPending} onChange={(event) => setSelectedFileId(event.target.value)}>
        <option value="">{t("selectCaseDocument")}</option>
        {choices.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}
      </select>
      {uploads.isPending ? <p role="status" className="text-muted">{t("loadingAuthorizedDocuments")}</p> : null}
      {uploads.isError ? <div role="alert" className="flex flex-wrap items-center gap-2 text-danger"><span>{t("documentLibraryError")}</span><Button type="button" variant="text" onClick={() => void uploads.refetch()}>{t("retry")}</Button></div> : null}
      {uploads.isSuccess && choices.length === 0 && !uploads.hasNextPage ? <p className="text-muted">{t("noAvailableCaseDocuments")}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" disabled={!selectedFileId || mutation.isPending || documents.isPending || documents.isError} onClick={() => mutation.mutate({ fileId: selectedFileId, action: "link" })}>{t("linkDocument")}</Button>
        {uploads.hasNextPage ? <Button type="button" variant="text" disabled={uploads.isFetchingNextPage} onClick={() => void uploads.fetchNextPage()}>{uploads.isFetchingNextPage ? t("loadingMore") : t("loadMore")}</Button> : null}
      </div>
    </div>}
    {error ? <p role="alert" className="text-danger">{error}</p> : null}
    {message ? <p role="status" className="text-muted">{message}</p> : null}
  </div>;
}
