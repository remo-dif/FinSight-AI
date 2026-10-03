import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { fetchInitialCaseQueue } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Triage"
};

export default async function Home() {
  const initialQueue = await fetchInitialCaseQueue();
  return <AppShell activeRoute="triage" initialQueue={initialQueue} />;
}
