import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Entity Graph"
};

export default function GraphPage() {
  return <AppShell activeRoute="graph" />;
}
