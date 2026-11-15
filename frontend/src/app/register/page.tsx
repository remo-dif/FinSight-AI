import type { Metadata } from "next";
import { headers } from "next/headers";
import { RegisterPage } from "@/components/auth/register-page";
import { normalizeLocale } from "@/i18n/config";
import { translate } from "@/i18n/messages";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const locale = normalizeLocale((await headers()).get("x-locale") ?? undefined);
  return { title: translate(locale, "register") };
}

export default function Register() {
  return <RegisterPage />;
}
