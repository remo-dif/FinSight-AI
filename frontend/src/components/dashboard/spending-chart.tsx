"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Panel } from "@/components/ui/panel";

const data = [
  { name: "Housing", value: 1500, color: "#0b84a5" },
  { name: "Groceries", value: 420, color: "#16a064" },
  { name: "Transport", value: 260, color: "#f59e0b" },
  { name: "Subscriptions", value: 78, color: "#dc3055" }
];

export function SpendingChart() {
  return (
    <Panel className="h-[360px]" aria-labelledby="spending-mix-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="spending-mix-heading" className="text-lg font-semibold">Spending Mix</h2>
          <p className="mt-1 text-sm text-muted">Current month by category</p>
        </div>
      </div>
      <div className="mt-4 h-[210px]" role="img" aria-label="Pie chart of current month spending by category">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={58} outerRadius={92}>
              {data.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => `$${value}`} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-2 text-sm" aria-label="Spending category legend">
        {data.map((entry) => (
          <li key={entry.name} className="flex items-center gap-2 text-muted">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="truncate">{entry.name}</span>
            <span className="ml-auto font-semibold text-foreground">${entry.value}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
