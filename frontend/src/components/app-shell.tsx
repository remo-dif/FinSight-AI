"use client";

import Link from "next/link";
import type { Route } from "next";
import { CasesWorkspace, TriageWorkspace } from "@/components/dashboard/dashboard-workspace";
import { EvidenceWorkspace } from "@/components/evidence/evidence-workspace";
import { MobileNavigation, type MobileNavigationItem } from "@/components/mobile-navigation";
import { localeLabels, locales, useLocale, useLocalizedPath, useTranslations } from "@/i18n/context";
import type { MessageKey } from "@/i18n/messages";
import type { InitialCaseQueue } from "@/lib/server-data";
import {
  BriefcaseBusiness,
  Construction,
  Database,
  FileSearch,
  Gauge,
  LogIn,
  Network,
  Settings,
  ShieldAlert,
  Siren
} from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { useSessionStore } from "@/store/session";

type WorkspaceRoute = "triage" | "cases" | "graph" | "evidence" | "data" | "controls";

const navigation: Array<{ id: WorkspaceRoute; label: MessageKey; href: `/${string}`; icon: typeof Gauge; comingSoon?: boolean }> = [
  { id: "triage", label: "triage", href: "/", icon: Gauge },
  { id: "cases", label: "cases", href: "/cases", icon: BriefcaseBusiness },
  { id: "graph", label: "graph", href: "/graph", icon: Network, comingSoon: true },
  { id: "evidence", label: "evidence", href: "/evidence", icon: FileSearch },
  { id: "data", label: "data", href: "/data", icon: Database, comingSoon: true }
];

const controlsNavigation = { id: "controls" as const, label: "controls" as const, href: "/controls" as const, icon: Settings, comingSoon: true };

const mobileNavigation: Array<Omit<MobileNavigationItem, "label"> & { label: MessageKey }> = [
  ...navigation.filter((item) => !item.comingSoon),
  ...navigation.filter((item) => item.comingSoon),
  controlsNavigation
].map(({ id, label, href, comingSoon }) => ({ id, label, href, comingSoon }));

const routeCopy: Record<WorkspaceRoute, { eyebrow: MessageKey; title: MessageKey; description: MessageKey; comingSoon?: boolean }> = {
  triage: {
    eyebrow: "fraudCommandCenter",
    title: "triageTitle",
    description: "triageDescription"
  },
  cases: {
    eyebrow: "caseOperations",
    title: "casesTitle",
    description: "casesDescription"
  },
  graph: {
    eyebrow: "entityIntelligence",
    title: "graphTitle",
    description: "graphDescription",
    comingSoon: true
  },
  evidence: {
    eyebrow: "evidenceReview",
    title: "evidenceTitle",
    description: "evidenceDescription"
  },
  data: {
    eyebrow: "investigationData",
    title: "dataTitle",
    description: "dataDescription",
    comingSoon: true
  },
  controls: {
    eyebrow: "workspaceControls",
    title: "controlsTitle",
    description: "controlsDescription",
    comingSoon: true
  }
};

export function AppShell({
  activeRoute,
  initialQueue,
  selectedCaseId
}: {
  activeRoute: WorkspaceRoute;
  initialQueue?: InitialCaseQueue;
  selectedCaseId?: string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const switchLocale = useLocalizedPath();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  const accessToken = useSessionStore((state) => state.accessToken);
  const currentDestination = `${pathname}${searchParams.size ? `?${searchParams.toString()}` : ""}`;
  const copy = routeCopy[activeRoute];
  const isComingSoon = Boolean(copy.comingSoon);
  const localizedHref = (href: string) => `${locale === "en" ? "" : `/${locale}`}${href === "/" ? "" : href}` || "/";

  return (
    <main className="min-h-[100dvh] overflow-x-clip bg-background text-foreground">
      <a
        className="sr-only rounded-md bg-panel px-3 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50"
        href="#dashboard"
      >
        {t("skipToDashboard")}
      </a>

      <div className="grid min-h-[100dvh] lg:grid-cols-[244px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-panel lg:flex lg:flex-col" aria-label={t("sidebarNavigation")}>
          <div className="flex h-16 items-center gap-3 border-b border-border px-5">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-danger/10 text-danger">
              <ShieldAlert aria-hidden className="h-5 w-5" />
            </span>
            <div>
              <p className="text-sm font-bold">FinSight AI</p>
              <p className="text-xs text-muted">{t("appTagline")}</p>
            </div>
          </div>
          <nav className="flex-1 space-y-1 px-3 py-4 text-sm font-medium" aria-label={t("workspaceNavigation")}>
            {navigation.map((item) => {
              const isActive = item.id === activeRoute;
              return (
                <Link
                  key={item.label}
                  className={`flex h-9 items-center gap-3 rounded-md px-3 transition ${
                    isActive
                      ? "bg-accent/10 text-accent"
                      : "text-muted hover:bg-background hover:text-foreground"
                  }`}
                  href={localizedHref(item.href) as Route}
                  aria-current={isActive ? "page" : undefined}
                >
                  <item.icon aria-hidden className="h-4 w-4" />
                  {t(item.label)}
                  {item.comingSoon ? (
                    <span className="ml-auto text-[10px] font-semibold uppercase tracking-wide">{t("comingSoon")}</span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-border p-3">
            <Link
              className={`flex min-h-9 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition ${
                activeRoute === "controls" ? "bg-accent/10 text-accent" : "text-muted hover:bg-background hover:text-foreground"
              }`}
              href={localizedHref("/controls") as Route}
              aria-current={activeRoute === "controls" ? "page" : undefined}
            >
              <Settings aria-hidden className="h-4 w-4" />
              {t("controls")}
              <span className="ml-auto text-[10px] font-semibold uppercase tracking-wide">{t("comingSoon")}</span>
            </Link>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-[env(safe-area-inset-top,0px)] z-20 border-b border-border bg-panel/95 backdrop-blur">
            <MobileNavigation activeRoute={activeRoute} items={mobileNavigation.map((item) => ({ ...item, href: localizedHref(item.href), label: t(item.label) })) as MobileNavigationItem[]} />
            <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:px-6 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-danger">
                  <Siren aria-hidden className="h-4 w-4" />
                  {t(copy.eyebrow)}
                </p>
                <h1 className="text-xl font-semibold leading-tight sm:text-2xl">{t(copy.title)}</h1>
                <label className="mt-2 inline-flex items-center gap-2 text-xs text-muted" htmlFor="locale-switcher">{t("language")}
                  <select id="locale-switcher" className="rounded border border-border bg-white px-2 py-1 text-foreground" value={locale} onChange={(event) => switchLocale(event.target.value as typeof locale)}>
                    {locales.map((item) => <option key={item} value={item}>{localeLabels[item]}</option>)}
                  </select>
                </label>
              </div>
              {!accessToken ? (
                <Link
                  className="inline-flex min-h-10 items-center justify-center gap-2 self-start rounded-md border border-border bg-white px-4 text-sm font-semibold text-accent transition hover:border-accent/60"
                  href={`${localizedHref("/login")}?returnTo=${encodeURIComponent(currentDestination)}` as Route}
                >
                  <LogIn aria-hidden className="h-4 w-4" />
                  {t("signIn")}
                </Link>
              ) : null}
            </div>
          </header>

          <div className="px-4 py-4 sm:px-6">
            {isComingSoon ? (
              <section id="dashboard" className="mx-auto max-w-3xl py-8 sm:py-16" aria-labelledby="coming-soon-heading">
                <div className="rounded-lg border border-border bg-panel p-6 shadow-soft sm:p-8">
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-accent/10 text-accent">
                    <Construction aria-hidden className="h-5 w-5" />
                  </span>
                  <p className="mt-5 text-xs font-semibold uppercase tracking-wide text-accent">{t("comingSoon")}</p>
                  <h2 id="coming-soon-heading" className="mt-2 text-xl font-semibold">{t("unavailableWorkspace")}</h2>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">{t(copy.description)}</p>
                  <Link className="mt-6 inline-flex min-h-10 items-center rounded-md border border-border bg-white px-4 text-sm font-semibold text-accent transition hover:border-accent/60" href={localizedHref("/") as Route}>
                    {t("returnToTriage")}
                  </Link>
                </div>
              </section>
            ) : (
            <section id="dashboard" className="min-w-0 space-y-4" aria-labelledby="dashboard-heading">
              <div className="border-b border-border pb-4">
                <div className="max-w-3xl">
                  <h2 id="dashboard-heading" className="text-base font-semibold">{activeRoute === "triage" ? t("triageWorkspace") : activeRoute === "cases" ? t("caseInvestigation") : t("documentWorkspace")}</h2>
                  <p className="mt-1 text-sm text-muted">{t(copy.description)}</p>
                </div>
              </div>
              {activeRoute === "triage" ? <TriageWorkspace initialQueue={initialQueue} /> : null}
              {activeRoute === "cases" ? <CasesWorkspace initialQueue={initialQueue} initialSelectedId={selectedCaseId} /> : null}
              {activeRoute === "evidence" ? <EvidenceWorkspace /> : null}
            </section>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
