import { LucideIcon } from "lucide-react";
import { Panel } from "@/components/ui/panel";

type MetricCardProps = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone: "success" | "warning" | "danger" | "accent";
  trend?: string;
};

export function MetricCard({ label, value, detail, icon: Icon, tone, trend }: MetricCardProps) {
  const styles = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
    accent: "bg-accent/10 text-accent"
  }[tone];

  return (
    <Panel className="min-h-[126px] p-4 transition hover:border-accent/60">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</h3>
        <span className={`flex h-8 w-8 items-center justify-center rounded-md ${styles}`}>
          <Icon aria-hidden className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="text-2xl font-semibold leading-none">{value}</p>
        {trend ? <p className="text-xs font-semibold text-danger">{trend}</p> : null}
      </div>
      <p className="mt-3 text-xs leading-5 text-muted">{detail}</p>
    </Panel>
  );
}
