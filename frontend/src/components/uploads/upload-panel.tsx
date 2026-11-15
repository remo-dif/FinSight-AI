"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp, LoaderCircle, Lock, UploadCloud } from "lucide-react";
import { ChangeEvent, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { caseListQueryKey, uploadedDocumentsQueryKey, uploadFinancialFile } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/store/session";
import { useTranslations } from "@/i18n/context";

export function UploadPanel() {
  const userDataEpoch = useSessionStore((state) => state.userDataEpoch);
  return <UploadSession key={userDataEpoch} userDataEpoch={userDataEpoch} />;
}

function UploadSession({ userDataEpoch }: { userDataEpoch: number }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const inputId = useId();
  const statusId = useId();
  const [filename, setFilename] = useState<string>(t("noFileSelected"));
  const [file, setFile] = useState<File | null>(null);
  const [importCurrency, setImportCurrency] = useState("");
  const isCsv = file?.name.toLowerCase().endsWith(".csv") ?? false;
  const upload = useMutation({
    mutationFn: (request: { file: File; currency?: string; userDataEpoch: number }) =>
      uploadFinancialFile(request.file, request.currency, request.userDataEpoch),
    onSuccess: async (_data, request) => {
      if (useSessionStore.getState().userDataEpoch !== request.userDataEpoch) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: caseListQueryKey() }),
        queryClient.invalidateQueries({ queryKey: uploadedDocumentsQueryKey })
      ]);
    }
  });

  const statusMessage = upload.isSuccess
    ? `${upload.data.status}: ${upload.data.imported} imported, ${upload.data.indexed} indexed`
    : upload.isError
      ? upload.error.message
      : upload.isPending
        ? t("uploadingProcessing")
        : t("filesValidated");

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setImportCurrency("");
    setFilename(selected?.name ?? t("noFileSelected"));
    upload.reset();
  }

  return (
    <Panel as="section" className="p-4" aria-labelledby="uploads-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="uploads-heading" className="text-base font-semibold">{t("uploadDocument")}</h2>
          <p className="mt-1 text-sm text-muted">{t("uploadDescription")}</p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-success/10 text-success">
          <Lock aria-hidden className="h-5 w-5" />
        </span>
      </div>
      <label
        className="mt-4 flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-border bg-background px-4 text-center transition hover:border-accent hover:bg-accent/5 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/30"
        htmlFor={inputId}
      >
        <UploadCloud aria-hidden className="h-8 w-8 text-accent" />
        <span className="mt-3 text-sm font-semibold">{t("chooseDocument")}</span>
        <span className="mt-1 max-w-full truncate text-xs text-muted" aria-live="polite">{filename}</span>
        <input
          id={inputId}
          className="sr-only"
          type="file"
          accept=".csv,.pdf,.png,.jpg,.jpeg"
          aria-describedby={`${inputId}-hint ${statusId}`}
          onChange={onFile}
          disabled={upload.isPending}
        />
        <span id={`${inputId}-hint`} className="sr-only">{t("acceptedFileTypes")}</span>
      </label>
      {isCsv && (
        <div className="mt-4 space-y-2">
          <label htmlFor={`${inputId}-currency`} className="block text-sm font-medium">{t("csvCurrency")}</label>
          <select
            id={`${inputId}-currency`}
            value={importCurrency}
            onChange={(event) => { setImportCurrency(event.target.value); upload.reset(); }}
            disabled={upload.isPending}
            aria-describedby={`${inputId}-currency-hint`}
            className="min-h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
          >
            <option value="">{t("useCurrencyColumn")}</option>
            {["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD"].map((currency) => (
              <option key={currency} value={currency}>{currency}</option>
            ))}
          </select>
          <p id={`${inputId}-currency-hint`} className="text-xs text-muted">
            {t("uploadCurrencyHint")}
          </p>
        </div>
      )}
      <div className="mt-4 flex items-center justify-between gap-3">
        <p
          id={statusId}
          className={cn("text-xs text-muted", upload.isError && "font-medium text-danger")}
          role={upload.isError ? "alert" : "status"}
          aria-live={upload.isError ? "assertive" : "polite"}
        >
          {statusMessage}
        </p>
        <Button
          type="button"
          disabled={!file || upload.isPending}
          onClick={() => file && upload.mutate({ file, currency: isCsv ? importCurrency : undefined, userDataEpoch })}
          aria-busy={upload.isPending}
        >
          {upload.isPending ? (
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <FileUp aria-hidden className="h-4 w-4" />
          )}
          {upload.isPending ? t("uploading") : t("upload")}
        </Button>
      </div>
      <ol className="mt-4 grid grid-cols-1 gap-2 text-xs font-medium text-muted sm:grid-cols-3" aria-label={t("uploadProcessingSteps")}>
        {(["validate", "extract", "link"] as const).map((key) => (
          <li key={key} className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-white p-2 transition hover:border-accent/60 hover:text-foreground">
            <FileUp aria-hidden className="h-4 w-4 text-accent" />
            {t(key)}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
