import { LucideIcon } from "lucide-react";
import { Panel } from "@/components/ui/panel";

type MetricCardProps = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone: "success" | "warning" | "danger" | "accent";
};

export function MetricCard({ label, value, detail, icon: Icon, tone }: MetricCardProps) {
  const styles = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
    accent: "bg-accent/10 text-accent"
  }[tone];

  return (
    <Panel className="min-h-[142px] transition hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-lg">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-muted">{label}</h3>
        <span className={`flex h-9 w-9 items-center justify-center rounded-md ${styles}`}>
          <Icon aria-hidden className="h-5 w-5" />
        </span>
      </div>
      <p className="mt-4 text-3xl font-bold leading-none">{value}</p>
      <p className="mt-3 text-sm leading-5 text-muted">{detail}</p>
    </Panel>
  );
}
