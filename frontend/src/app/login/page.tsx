import type { Metadata } from "next";
import { headers } from "next/headers";
import { LoginPage } from "@/components/auth/login-page";
import { normalizeLocale } from "@/i18n/config";
import { translate } from "@/i18n/messages";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined);
  return { title: translate(locale, "signIn") };
}

export default function Login() {
  return <LoginPage />;
}
