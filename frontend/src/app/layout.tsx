import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Providers } from "@/components/providers";
import { headers } from "next/headers";
import { normalizeLocale } from "@/i18n/config";

// Per-request CSP nonces cannot be embedded into prerendered/cached HTML.
export const dynamic = "force-dynamic";

const baseMetadata: Metadata = {
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

export async function generateMetadata(): Promise<Metadata> {
  const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined);
  const italian = locale === "it";
  const title = italian ? "FinSight AI — Area di indagine antifrode" : "FinSight AI — Fraud Investigation Workspace";
  const description = italian ? "Triage antifrode assistito dall'IA, revisione dei casi e gestione delle evidenze per i team operativi." : String(baseMetadata.description);
  return { ...baseMetadata, title: { template: "%s | FinSight AI", default: title }, description, openGraph: { ...baseMetadata.openGraph, title, description, locale: italian ? "it_IT" : "en_US" } };
}

export const viewport: Viewport = {
  themeColor: "#123f65"
};

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined);
  return (
    <html lang={locale}>
      <body>
        <Providers locale={locale}>{children}</Providers>
      </body>
    </html>
  );
}
