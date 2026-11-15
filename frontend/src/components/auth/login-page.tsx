"use client";

import Link from "next/link";
import type { Route } from "next";
import { ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthPanel } from "@/components/auth/auth-panel";
import { localeLabels, locales, localizePath, useLocale, useLocalizedPath, useTranslations } from "@/i18n/context";
import { restoreSession } from "@/lib/api";
import { useSessionStore } from "@/store/session";

export function safeReturnTo(value: string | null, locale: ReturnType<typeof useLocale>) {
  const fallback = localizePath("/", locale);
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  try {
    const parsed = new URL(value, "https://finsight.local");
    if (parsed.origin !== "https://finsight.local") return fallback;
    const segments = parsed.pathname.split("/").filter(Boolean);
    const route = locales.includes(segments[0] as (typeof locales)[number]) ? segments[1] : segments[0];
    if (route === "login" || route === "register") return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function LoginPage() {
  const t = useTranslations();
  const locale = useLocale();
  const switchLocale = useLocalizedPath();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [checkingSession, setCheckingSession] = useState(true);
  const returnTo = safeReturnTo(searchParams.get("returnTo"), locale);
  const registerHref = `${localizePath("/register", locale)}?returnTo=${encodeURIComponent(returnTo)}`;

  useEffect(() => {
    let active = true;
    void restoreSession().then(() => {
      if (!active) return;
      if (useSessionStore.getState().accessToken) router.replace(returnTo as Route);
      else setCheckingSession(false);
    });
    return () => { active = false; };
  }, [returnTo, router]);

  return (
    <main className="grid min-h-[100dvh] place-items-center bg-background px-4 py-8 text-foreground">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-danger/10 text-danger">
            <ShieldAlert aria-hidden className="h-5 w-5" />
          </span>
          <div>
            <p className="font-bold">FinSight AI</p>
            <p className="text-xs text-muted">{t("appTagline")}</p>
          </div>
        </div>
        <h1 className="text-2xl font-semibold">{t("loginPageTitle")}</h1>
        <p className="mt-2 text-sm leading-6 text-muted">{t("loginPageDescription")}</p>
        <label className="mt-4 inline-flex items-center gap-2 text-xs text-muted" htmlFor="login-locale-switcher">
          {t("language")}
          <select id="login-locale-switcher" className="rounded border border-border bg-white px-2 py-1 text-foreground" value={locale} onChange={(event) => switchLocale(event.target.value as typeof locale)}>
            {locales.map((item) => <option key={item} value={item}>{localeLabels[item]}</option>)}
          </select>
        </label>
        <div className="mt-6">
          {searchParams.get("registered") === "1" ? <p className="mb-3 text-sm text-success" role="status">{t("registrationComplete")}</p> : null}
          {checkingSession ? (
            <p className="rounded-lg border border-border bg-panel p-4 text-sm text-muted shadow-soft" role="status">{t("loginCheckingSession")}</p>
          ) : (
            <AuthPanel registrationEnabled={false} onSignedIn={() => router.replace(returnTo as Route)} />
          )}
        </div>
        <Link className="mt-5 inline-flex min-h-10 items-center text-sm font-semibold text-accent underline-offset-4 hover:underline" href={localizePath("/", locale) as Route}>
          {t("continueWithoutSigningIn")}
        </Link>
        <p className="mt-2 text-sm text-muted">
          {t("needAccount")} {" "}
          <Link className="font-semibold text-accent underline-offset-4 hover:underline" href={registerHref as Route}>{t("createAccount")}</Link>
        </p>
      </div>
    </main>
  );
}
