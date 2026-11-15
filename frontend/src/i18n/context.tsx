"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { defaultLocale, isLocale, localeLabels, locales, type Locale } from "./config";
import { translate } from "./messages";

const LocaleContext = createContext<Locale>(defaultLocale);

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const pathname = usePathname() || "/";
  const pathLocale = pathname.split("/").filter(Boolean)[0];
  const activeLocale = isLocale(pathLocale) ? pathLocale : pathLocale === "" ? locale : "en";
  useEffect(() => {
    document.documentElement.lang = activeLocale;
  }, [activeLocale]);
  return <LocaleContext.Provider value={activeLocale}>{children}</LocaleContext.Provider>;
}

export function useLocale() { return useContext(LocaleContext); }

export function useTranslations() {
  const locale = useLocale();
  return useMemo(() => (key: string, values?: Record<string, string | number>) => translate(locale, key, values), [locale]);
}

export function useLocalizedPath() {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  return (nextLocale: Locale) => {
    const withoutLocale = pathname.split("/").filter(Boolean);
    if (isLocale(withoutLocale[0])) withoutLocale.shift();
    const path = withoutLocale.length ? `/${withoutLocale.join("/")}` : "/";
    const query = searchParams.toString();
    const prefix = nextLocale === defaultLocale ? "" : `/${nextLocale}`;
    router.push(`${prefix}${path}${query ? `?${query}` : ""}` as never);
  };
}

export { localeLabels, locales };
