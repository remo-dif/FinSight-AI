import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Controls"
};

export default function ControlsPage() {
  return <AppShell activeRoute="controls" />;
}
