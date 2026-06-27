import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: {
    template: "%s | FinSight AI",
    default: "FinSight AI — Fraud Investigation Workspace"
  },
  description: "AI-assisted fraud triage, case review, and evidence management for operations teams.",
  robots: { index: false, follow: false },
  openGraph: {
    title: "FinSight AI — Fraud Investigation Workspace",
    description: "AI-assisted fraud triage, case review, and evidence management for operations teams.",
    type: "website",
    locale: "en_US"
  },
  twitter: { card: "summary" }
};

export const viewport: Viewport = {
  themeColor: "#123f65"
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
