import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Data Controls"
};

export default function DataPage() {
  return <AppShell activeRoute="data" />;
}
