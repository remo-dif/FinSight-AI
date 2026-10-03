import { demoTransactions, InvestigationCase, Transaction } from "@/lib/api";
import { Panel } from "@/components/ui/panel";

export function formatAmount(transaction: Transaction) {
  const value = Number(transaction.amount);
  return getCurrencyFormatter(transaction.currency || "USD").format(value);
}

const currencyFormatters = new Map<string, Intl.NumberFormat>();

function getCurrencyFormatter(currency: string) {
  let formatter = currencyFormatters.get(currency);
  if (!formatter) {
    formatter = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2
    });
    currencyFormatters.set(currency, formatter);
  }
  return formatter;
}

function statusFor(status: InvestigationCase["status"]) {
  return {
    new: "New",
    needs_evidence: "Needs evidence",
    escalated: "Escalated",
    resolved: "Resolved"
  }[status];
}

type TransactionsTableProps = {
  transactions?: InvestigationCase[];
  selectedId?: string;
  onSelect?: (caseRecord: InvestigationCase) => void;
};

export function TransactionsTable({
  transactions = demoTransactions,
  selectedId,
  onSelect
}: TransactionsTableProps) {
  return (
    <Panel as="section" className="p-0" aria-labelledby="recent-transactions-heading">
      <div className="flex flex-col gap-1 border-b border-border px-4 py-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="recent-transactions-heading" className="text-base font-semibold">Alert queue</h2>
          <p className="text-sm text-muted">Review cases by transaction, signal, ownership, and status</p>
        </div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{transactions.length} cases</p>
      </div>
      <ul className="divide-y divide-border md:hidden" aria-label="Fraud cases">
        {transactions.map((caseRecord) => {
          const isSelected = caseRecord.id === selectedId;
          return (
            <li key={caseRecord.id}>
              <button
                type="button"
                className={`grid w-full gap-3 p-4 text-left transition hover:bg-accent/5 ${isSelected ? "bg-accent/10" : "bg-panel"}`}
                onClick={() => onSelect?.(caseRecord)}
                aria-pressed={isSelected}
              >
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block font-semibold text-accent">{caseRecord.id}</span>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.assignee_name ?? "Unassigned"}</span>
                  </span>
                </span>
                <span className="flex items-start justify-between gap-4">
                  <span className="min-w-0">
                    <span className="block font-semibold">{caseRecord.merchant}</span>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.category || caseRecord.description}</span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block font-semibold">{formatAmount(caseRecord)}</span>
                    <span className="mt-1 block text-xs text-muted">{statusFor(caseRecord.status)}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="hidden overflow-hidden md:block">
        <table className="w-full table-fixed border-collapse text-sm">
          <caption className="sr-only">Fraud cases with case, assignee, merchant, signal, amount, and status</caption>
          <thead>
            <tr className="border-y border-border bg-background text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-semibold" scope="col">Case / Assignee</th>
              <th className="px-3 py-3 font-semibold" scope="col">Entity / Merchant</th>
              <th className="px-3 py-3 font-semibold" scope="col">Primary signal</th>
              <th className="px-3 py-3 text-right font-semibold" scope="col">Amount</th>
              <th className="px-3 py-3 font-semibold" scope="col">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {transactions.map((caseRecord) => {
              const isSelected = caseRecord.id === selectedId;
              return (
                <tr
                  key={caseRecord.id}
                  className={`cursor-pointer transition hover:bg-accent/5 ${isSelected ? "bg-accent/10" : ""}`}
                  onClick={() => onSelect?.(caseRecord)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect?.(caseRecord);
                    }
                  }}
                  tabIndex={0}
                  aria-selected={isSelected}
                >
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="text-left font-semibold text-accent underline-offset-4 hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect?.(caseRecord);
                      }}
                    >
                      {caseRecord.id}
                    </button>
                    <span className="mt-1 block text-xs text-muted">{caseRecord.assignee_name ?? "Unassigned"}</span>
                  </td>
                  <th className="px-3 py-3 text-left font-semibold" scope="row">
                    <span className="block">{caseRecord.merchant}</span>
                    <span className="text-xs font-normal text-muted">{caseRecord.source} source - {caseRecord.posted_at}</span>
                  </th>
                  <td className="px-3 py-3 text-muted">{caseRecord.category || caseRecord.description}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold">{formatAmount(caseRecord)}</td>
                  <td className="whitespace-nowrap px-3 py-3">{statusFor(caseRecord.status)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
