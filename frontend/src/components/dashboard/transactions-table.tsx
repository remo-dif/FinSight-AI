import { demoTransactions, Transaction } from "@/lib/api";
import { Panel } from "@/components/ui/panel";

export function TransactionsTable({ transactions = demoTransactions }: { transactions?: Transaction[] }) {
  return (
    <Panel aria-labelledby="recent-transactions-heading">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="recent-transactions-heading" className="text-lg font-semibold">Recent Transactions</h2>
          <p className="text-sm text-muted">Normalized feed with AI categories</p>
        </div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{transactions.length} items</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-sm">
          <caption className="sr-only">Recent financial transactions with date, merchant, category, and amount</caption>
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-2 py-3 font-semibold" scope="col">Date</th>
              <th className="px-2 py-3 font-semibold" scope="col">Merchant</th>
              <th className="px-2 py-3 font-semibold" scope="col">Category</th>
              <th className="px-2 py-3 text-right font-semibold" scope="col">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {transactions.map((transaction) => (
              <tr key={transaction.id} className="transition hover:bg-background">
                <td className="whitespace-nowrap px-2 py-3 text-muted">{transaction.posted_at}</td>
                <th className="px-2 py-3 text-left font-semibold" scope="row">{transaction.merchant}</th>
                <td className="px-2 py-3 text-muted">{transaction.category}</td>
                <td className="whitespace-nowrap px-2 py-3 text-right font-semibold">{transaction.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
