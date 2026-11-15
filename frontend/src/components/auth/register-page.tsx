"use client";

import Link from "next/link";
import type { Route } from "next";
import { ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthPanel } from "@/components/auth/auth-panel";
import { safeReturnTo } from "@/components/auth/login-page";
import { localeLabels, locales, localizePath, useLocale, useLocalizedPath, useTranslations } from "@/i18n/context";

export function RegisterPage() {
  const t = useTranslations();
  const locale = useLocale();
  const switchLocale = useLocalizedPath();
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("returnTo"), locale);
  const loginHref = `${localizePath("/login", locale)}?returnTo=${encodeURIComponent(returnTo)}`;

  return (
    <main className="grid min-h-[100dvh] place-items-center bg-background px-4 py-8 text-foreground">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-danger/10 text-danger">
            <ShieldAlert aria-hidden className="h-5 w-5" />
          </span>
          <div><p className="font-bold">FinSight AI</p><p className="text-xs text-muted">{t("appTagline")}</p></div>
        </div>
        <h1 className="text-2xl font-semibold">{t("registerPageTitle")}</h1>
        <p className="mt-2 text-sm leading-6 text-muted">{t("registerPageDescription")}</p>
        <label className="mt-4 inline-flex items-center gap-2 text-xs text-muted" htmlFor="register-locale-switcher">
          {t("language")}
          <select id="register-locale-switcher" className="rounded border border-border bg-white px-2 py-1 text-foreground" value={locale} onChange={(event) => switchLocale(event.target.value as typeof locale)}>
            {locales.map((item) => <option key={item} value={item}>{localeLabels[item]}</option>)}
          </select>
        </label>
        <div className="mt-6">
          <AuthPanel initialMode="register" onRegistered={() => router.replace(`${loginHref}&registered=1` as Route)} />
        </div>
        <p className="mt-5 text-sm text-muted">
          {t("alreadyHaveAccount")} {" "}
          <Link className="font-semibold text-accent underline-offset-4 hover:underline" href={loginHref as Route}>{t("signIn")}</Link>
        </p>
        <Link className="mt-2 inline-flex min-h-10 items-center text-sm font-semibold text-accent underline-offset-4 hover:underline" href={localizePath("/", locale) as Route}>{t("continueWithoutSigningIn")}</Link>
      </div>
    </main>
  );
}
