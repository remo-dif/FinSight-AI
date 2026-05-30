"use client";

import { useMutation } from "@tanstack/react-query";
import { FileUp, LoaderCircle, Lock, UploadCloud } from "lucide-react";
import { ChangeEvent, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { uploadFinancialFile } from "@/lib/api";
import { cn } from "@/lib/utils";

export function UploadPanel() {
  const inputId = useId();
  const statusId = useId();
  const [filename, setFilename] = useState<string>("No file selected");
  const [file, setFile] = useState<File | null>(null);
  const upload = useMutation({ mutationFn: uploadFinancialFile });

  const statusMessage = upload.isSuccess
    ? `${upload.data.status}: ${upload.data.imported} imported, ${upload.data.indexed} indexed`
    : upload.isError
      ? upload.error.message
      : upload.isPending
        ? "Uploading and processing your file..."
        : "Files are validated before processing.";

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setFilename(selected?.name ?? "No file selected");
    upload.reset();
  }

  return (
    <Panel aria-labelledby="uploads-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="uploads-heading" className="text-lg font-semibold">Secure Upload</h2>
          <p className="mt-1 text-sm text-muted">CSV, PDF, PNG, JPG, JPEG</p>
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
        <span className="mt-3 text-sm font-semibold">Select a financial file</span>
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
        <span id={`${inputId}-hint`} className="sr-only">Accepted file types are CSV, PDF, PNG, JPG, and JPEG.</span>
      </label>
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
          onClick={() => file && upload.mutate(file)}
          aria-busy={upload.isPending}
        >
          {upload.isPending ? (
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <FileUp aria-hidden className="h-4 w-4" />
          )}
          {upload.isPending ? "Uploading" : "Upload"}
        </Button>
      </div>
      <ol className="mt-4 grid grid-cols-1 gap-2 text-xs font-medium text-muted sm:grid-cols-3" aria-label="Upload processing steps">
        {["Validate", "Normalize", "Categorize"].map((step) => (
          <li key={step} className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-white p-2 transition hover:border-accent/60 hover:text-foreground">
            <FileUp aria-hidden className="h-4 w-4 text-accent" />
            {step}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
