import { demoTransactions, Transaction } from "@/lib/api";
import { Panel } from "@/components/ui/panel";

export function riskFor(transaction: Transaction) {
  const amount = Math.abs(Number(transaction.amount));
  if (amount > 1000 || transaction.category.toLowerCase().includes("new payee")) {
    return { label: "High", className: "bg-danger/10 text-danger", score: 92 };
  }
  if (amount > 500 || transaction.category.toLowerCase().includes("geo")) {
    return { label: "Elevated", className: "bg-warning/10 text-warning", score: 78 };
  }
  return { label: "Review", className: "bg-accent/10 text-accent", score: 61 };
}

export function formatAmount(transaction: Transaction) {
  const value = Number(transaction.amount);
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: transaction.currency || "USD",
    maximumFractionDigits: 2
  }).format(value);
}

function statusFor(index: number) {
  return index === 0 ? "Needs evidence" : index === 1 ? "Escalated" : "New";
}

function ownerFor(index: number) {
  return index === 1 ? "Risk Ops" : "Unassigned";
}

function slaFor(index: number) {
  return index === 0 ? "42m" : index === 1 ? "2h 15m" : "3h 40m";
}

type TransactionsTableProps = {
  transactions?: Transaction[];
  selectedId?: string;
  onSelect?: (transaction: Transaction) => void;
};

export function TransactionsTable({
  transactions = demoTransactions,
  selectedId,
  onSelect
}: TransactionsTableProps) {
  return (
    <Panel className="p-0" aria-labelledby="recent-transactions-heading">
      <div className="flex flex-col gap-1 border-b border-border px-4 py-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="recent-transactions-heading" className="text-base font-semibold">Alert queue</h2>
          <p className="text-sm text-muted">Pick the next case by risk, SLA, signal, and owner</p>
        </div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{transactions.length} open items</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <caption className="sr-only">Open fraud alerts with case, risk, entity, signal, amount, SLA, status, and owner</caption>
          <thead>
            <tr className="border-y border-border bg-background text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-semibold" scope="col">Case</th>
              <th className="px-3 py-3 font-semibold" scope="col">Risk</th>
              <th className="px-3 py-3 font-semibold" scope="col">Entity / Merchant</th>
              <th className="px-3 py-3 font-semibold" scope="col">Primary signal</th>
              <th className="px-3 py-3 text-right font-semibold" scope="col">Amount</th>
              <th className="px-3 py-3 font-semibold" scope="col">SLA</th>
              <th className="px-3 py-3 font-semibold" scope="col">Status</th>
              <th className="px-4 py-3 font-semibold" scope="col">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {transactions.map((transaction, index) => {
              const risk = riskFor(transaction);
              const isSelected = transaction.id === selectedId;
              return (
                <tr
                  key={transaction.id}
                  className={`cursor-pointer transition hover:bg-accent/5 ${isSelected ? "bg-accent/10" : ""}`}
                  onClick={() => onSelect?.(transaction)}
                  aria-selected={isSelected}
                >
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="text-left font-semibold text-accent underline-offset-4 hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect?.(transaction);
                      }}
                    >
                      {transaction.id}
                    </button>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex min-w-20 justify-center rounded-md px-2 py-1 text-xs font-semibold ${risk.className}`}>
                      {risk.label} {risk.score}
                    </span>
                  </td>
                  <th className="px-3 py-3 text-left font-semibold" scope="row">
                    <span className="block">{transaction.merchant}</span>
                    <span className="text-xs font-normal text-muted">{transaction.source} source - {transaction.posted_at}</span>
                  </th>
                  <td className="px-3 py-3 text-muted">{transaction.category || transaction.description}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold">{formatAmount(transaction)}</td>
                  <td className="whitespace-nowrap px-3 py-3">
                    <span className={index === 0 ? "font-semibold text-danger" : "text-muted"}>{slaFor(index)}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="rounded-md bg-background px-2 py-1 text-xs font-semibold text-muted">
                      {statusFor(index)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{ownerFor(index)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
