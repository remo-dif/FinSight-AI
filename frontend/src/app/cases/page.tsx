import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { fetchInitialCaseQueue } from "@/lib/server-data";
import { headers } from "next/headers";
import { normalizeLocale } from "@/i18n/config";
import { translate } from "@/i18n/messages";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined);
  return { title: translate(locale, "cases") };
}

export default async function CasesPage({
  searchParams
}: {
  searchParams: Promise<{ case?: string }>;
}) {
  const selectedCaseId = (await searchParams).case;
  const initialQueue = await fetchInitialCaseQueue();
  return <AppShell activeRoute="cases" initialQueue={initialQueue} selectedCaseId={selectedCaseId} />;
}
