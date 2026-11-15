import { Panel } from "@/components/ui/panel";
import { useTranslations } from "@/i18n/context";

export type SpendingChartDatum = {
  name: string;
  value: number;
  color: string;
};

const defaultData: SpendingChartDatum[] = [
  { name: "Velocity spike", value: 42, color: "#be123c" },
  { name: "New payee", value: 31, color: "#b45309" },
  { name: "Geo mismatch", value: 18, color: "#0f766e" },
  { name: "Round amount", value: 9, color: "#0369a1" }
];

export function SpendingChart({ data = defaultData }: { data?: SpendingChartDatum[] }) {
  const t = useTranslations();
  const chartData = data.length ? data : defaultData;
  const max = Math.max(...chartData.map((item) => item.value), 1);

  return (
    <Panel as="section" className="h-full p-4" aria-labelledby="risk-drivers-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="risk-drivers-heading" className="text-base font-semibold">{t("riskDrivers")}</h2>
          <p className="mt-1 text-sm text-muted">{t("topSignals")}</p>
        </div>
        <span className="rounded-md bg-danger/10 px-2 py-1 text-xs font-semibold text-danger">{t("rulesAi")}</span>
      </div>

      <ul className="mt-5 space-y-4" aria-label={t("riskDriverDistribution")}>
        {chartData.map((entry) => (
          <li key={entry.name}>
            <div className="mb-1 flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">{entry.name}</span>
              <span className="text-muted">{entry.value} alerts</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-background" role="img" aria-label={`${entry.name}: ${entry.value} alerts`}>
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.max((entry.value / max) * 100, 6)}%`, backgroundColor: entry.color }}
              />
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-5 rounded-md border border-border bg-background p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("modelCalibration")}</p>
        <p className="mt-1 text-sm leading-5">{t("calibrationText")}</p>
      </div>
    </Panel>
  );
}
