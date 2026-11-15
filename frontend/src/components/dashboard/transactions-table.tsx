import { demoTransactions, InvestigationCase, Transaction } from "@/lib/api";
import { Panel } from "@/components/ui/panel";
import { useLocale, useTranslations } from "@/i18n/context";
import { formatDate, formatNumber } from "@/i18n/format";
import type { Locale } from "@/i18n/config";

export function formatAmount(transaction: Transaction, locale: Locale = "en") {
  // Keep decimal strings exact, including cents above Number.MAX_SAFE_INTEGER.
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(transaction.amount);
  if (!match) return `${transaction.amount} ${transaction.currency}`;
  const [, sign, integer, decimals = ""] = match;
  const currency = transaction.currency;
  const formatter = getCurrencyFormatter(currency, locale);
  const whole = BigInt(integer);
  const signed = sign ? (whole === BigInt(0) ? -0 : -whole) : whole;
  const parts = formatter.formatToParts(signed);
  const fraction = decimals.padEnd(formatter.resolvedOptions().minimumFractionDigits ?? 0, "0");
  if (!parts.some(part => part.type === "fraction") && fraction) {
    let lastInteger = 0;
    parts.forEach((part, index) => { if (part.type === "integer") lastInteger = index; });
    const separator = new Intl.NumberFormat(locale === "it" ? "it-IT" : "en-US").formatToParts(1.1).find(part => part.type === "decimal")?.value ?? ".";
    parts.splice(lastInteger + 1, 0, { type: "decimal", value: separator }, { type: "fraction", value: fraction });
  }
  return parts.map(part => part.type === "fraction" ? fraction : part.value).join("");
}

const currencyFormatters = new Map<string, Intl.NumberFormat>();

function getCurrencyFormatter(currency: string, locale: Locale) {
  const key = `${locale}:${currency}`;
  let formatter = currencyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale === "it" ? "it-IT" : "en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2
    });
    currencyFormatters.set(key, formatter);
  }
  return formatter;
}

type TransactionsTableProps = {
  transactions?: InvestigationCase[];
  selectedId?: string;
  queueStatus?: "ready" | "loading" | "error";
  onSelect?: (caseRecord: InvestigationCase, options?: { focusDetail?: boolean }) => void;
};

export function TransactionsTable({
  transactions = demoTransactions,
  selectedId,
  queueStatus = "ready",
  onSelect
}: TransactionsTableProps) {
  const locale = useLocale();
  const t = useTranslations();
  const statusFor = (status: InvestigationCase["status"]) => ({
    new: t("statusNew"),
    needs_evidence: t("statusNeedsEvidence"),
    escalated: t("statusEscalated"),
    resolved: t("statusResolved")
  })[status];
  const hasUsableCases = transactions.length > 0;
  const queueMessage = queueStatus === "loading" && !hasUsableCases
    ? "Loading cases…"
    : queueStatus === "error" && !hasUsableCases
      ? "The case queue is unavailable. Retry to load live cases."
      : transactions.length === 0
        ? "No cases are available in the current queue."
        : null;
  const cachedDataWarning = queueStatus === "error" && hasUsableCases
    ? "Refresh failed. Showing the most recently loaded cases."
    : null;
  const queueGuidance = queueStatus === "loading"
    ? "The queue will appear when loading finishes."
    : queueStatus === "error"
      ? "Your current selection and drafts are unchanged."
      : "New cases will appear here when they are assigned or detected.";

  return (
    <Panel as="section" className="p-0" aria-labelledby="recent-transactions-heading">
      <div className="flex flex-col gap-1 border-b border-border px-4 py-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="recent-transactions-heading" className="text-base font-semibold">{t("alertQueue")}</h2>
          <p className="text-sm text-muted">{t("alertQueueDescription")}</p>
        </div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("casesCount", { count: formatNumber(transactions.length, locale) })}</p>
      </div>
      {cachedDataWarning ? (
        <div className="border-b border-warning/30 bg-warning/10 px-4 py-3 text-sm">
          <p className="font-semibold text-warning">{cachedDataWarning}</p>
          <p className="mt-1 text-muted">You can continue reviewing these cases or retry the refresh.</p>
        </div>
      ) : null}
      {queueMessage ? (
        <div
          className="p-6 text-center"
          role={queueStatus === "error" ? undefined : "status"}
          aria-live={queueStatus === "error" ? undefined : "polite"}
        >
          <p className="font-semibold">{queueMessage}</p>
          <p className="mt-1 text-sm text-muted">
            {queueGuidance}
          </p>
        </div>
      ) : null}
      {!queueMessage ? (
      <>
      <ul className="divide-y divide-border md:hidden" aria-label={t("fraudCases")}>
        {transactions.map((caseRecord) => {
          const isSelected = caseRecord.id === selectedId;
          return (
            <li key={caseRecord.id}>
              <button
                type="button"
                className={`grid w-full gap-3 p-4 text-left transition hover:bg-accent/5 ${isSelected ? "bg-accent/10" : "bg-panel"}`}
                onClick={() => onSelect?.(caseRecord, { focusDetail: true })}
                aria-pressed={isSelected}
              >
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block break-all font-semibold text-accent">{caseRecord.id}</span>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.assignee_name ?? t("unassigned")}</span>
                  </span>
                </span>
                <span className="flex min-w-0 flex-wrap items-start justify-between gap-4">
                  <span className="min-w-0">
                    <span className="block font-semibold">{caseRecord.merchant}</span>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.category || caseRecord.description}</span>
                  </span>
                  <span className="min-w-0 max-w-full break-all text-right">
                    <span className="block font-semibold">{formatAmount(caseRecord, locale)}</span>
                    <span className="mt-1 block text-xs text-muted">{statusFor(caseRecord.status)}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="hidden overflow-x-auto md:block" tabIndex={0} role="region" aria-label={t("scrollableAlertQueue")}>
        <table className="w-full min-w-[800px] table-fixed border-collapse text-sm">
          <caption className="sr-only">{t("alertQueueCaption")}</caption>
          <thead>
            <tr className="border-y border-border bg-background text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-semibold" scope="col">{t("caseAssignee")}</th>
              <th className="px-3 py-3 font-semibold" scope="col">{t("entityMerchant")}</th>
              <th className="px-3 py-3 font-semibold" scope="col">{t("primarySignal")}</th>
              <th className="px-3 py-3 text-right font-semibold" scope="col">{t("amount")}</th>
              <th className="px-3 py-3 font-semibold" scope="col">{t("status")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {transactions.map((caseRecord) => {
              const isSelected = caseRecord.id === selectedId;
              return (
                <tr
                  key={caseRecord.id}
                  className={isSelected ? "bg-accent/10" : ""}
                >
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="min-h-8 break-all text-left font-semibold text-accent underline-offset-4 hover:underline"
                      onClick={() => onSelect?.(caseRecord)}
                      aria-pressed={isSelected}
                    >
                      {caseRecord.id}
                    </button>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.assignee_name ?? t("unassigned")}</span>
                  </td>
                  <th className="px-3 py-3 text-left font-semibold" scope="row">
                    <span className="block">{caseRecord.merchant}</span>
                    <span className="text-xs font-normal text-muted">{caseRecord.source} · {formatDate(caseRecord.posted_at, locale, { dateStyle: "medium", timeZone: "UTC" })}</span>
                  </th>
                  <td className="px-3 py-3 text-muted">{caseRecord.category || caseRecord.description}</td>
                  <td className="break-all px-3 py-3 text-right font-semibold">{formatAmount(caseRecord, locale)}</td>
                  <td className="break-words px-3 py-3">{statusFor(caseRecord.status)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </>
      ) : null}
    </Panel>
  );
}
