import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Triage"
};

export default function Home() {
  return <AppShell activeRoute="triage" />;
}
