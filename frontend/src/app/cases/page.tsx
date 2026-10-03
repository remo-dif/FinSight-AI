import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { fetchInitialCaseQueue } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Cases"
};

export default async function CasesPage() {
  const initialQueue = await fetchInitialCaseQueue();
  return <AppShell activeRoute="cases" initialQueue={initialQueue} />;
}
