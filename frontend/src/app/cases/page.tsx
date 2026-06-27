import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Cases"
};

export default function CasesPage() {
  return <AppShell activeRoute="cases" />;
}
