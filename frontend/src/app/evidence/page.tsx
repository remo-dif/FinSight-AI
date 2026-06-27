import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Evidence"
};

export default function EvidencePage() {
  return <AppShell activeRoute="evidence" />;
}
