import { demoTransactions, Transaction } from "@/lib/api";
import { Panel } from "@/components/ui/panel";

function riskFor(transaction: Transaction) {
  const amount = Math.abs(Number(transaction.amount));
  if (amount > 1000 || transaction.merchant.toLowerCase().includes("payroll")) return { label: "High", className: "bg-danger/10 text-danger" };
  if (amount > 75) return { label: "Medium", className: "bg-warning/10 text-warning" };
  return { label: "Low", className: "bg-success/10 text-success" };
}

function formatAmount(transaction: Transaction) {
  const value = Number(transaction.amount);
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: transaction.currency || "USD",
    maximumFractionDigits: 2
  }).format(value);
}

export function TransactionsTable({ transactions = demoTransactions }: { transactions?: Transaction[] }) {
  return (
    <Panel className="p-0" aria-labelledby="recent-transactions-heading">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div className="px-4 pt-4">
          <h2 id="recent-transactions-heading" className="text-base font-semibold">Alert queue</h2>
          <p className="text-sm text-muted">Transactions ranked for analyst review</p>
        </div>
        <p className="px-4 pt-4 text-xs font-semibold uppercase tracking-wide text-muted">{transactions.length} open items</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <caption className="sr-only">Open fraud alerts with risk, entity, signal, amount, status, and owner</caption>
          <thead>
            <tr className="border-y border-border bg-background text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-semibold" scope="col">Risk</th>
              <th className="px-3 py-3 font-semibold" scope="col">Date</th>
              <th className="px-3 py-3 font-semibold" scope="col">Entity / Merchant</th>
              <th className="px-3 py-3 font-semibold" scope="col">Primary signal</th>
              <th className="px-3 py-3 text-right font-semibold" scope="col">Amount</th>
              <th className="px-3 py-3 font-semibold" scope="col">Status</th>
              <th className="px-4 py-3 font-semibold" scope="col">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {transactions.map((transaction, index) => {
              const risk = riskFor(transaction);
              return (
                <tr key={transaction.id} className="transition hover:bg-accent/5">
                  <td className="px-4 py-3">
                    <span className={`inline-flex min-w-16 justify-center rounded-md px-2 py-1 text-xs font-semibold ${risk.className}`}>
                      {risk.label}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-muted">{transaction.posted_at}</td>
                  <th className="px-3 py-3 text-left font-semibold" scope="row">
                    <span className="block">{transaction.merchant}</span>
                    <span className="text-xs font-normal text-muted">{transaction.source} source</span>
                  </th>
                  <td className="px-3 py-3 text-muted">{transaction.category || transaction.description}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold">{formatAmount(transaction)}</td>
                  <td className="px-3 py-3">
                    <span className="rounded-md bg-background px-2 py-1 text-xs font-semibold text-muted">
                      {index === 0 ? "Needs evidence" : index === 1 ? "Escalated" : "New"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{index === 1 ? "Risk Ops" : "Unassigned"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
