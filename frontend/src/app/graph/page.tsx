import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { headers } from "next/headers";
import { normalizeLocale } from "@/i18n/config";
import { translate } from "@/i18n/messages";

export async function generateMetadata(): Promise<Metadata> { const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined); return { title: translate(locale, "graph") }; }

export default function GraphPage() {
  return <AppShell activeRoute="graph" />;
}
