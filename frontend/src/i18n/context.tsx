"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { defaultLocale, isLocale, localeLabels, locales, type Locale } from "./config";
import { translate, type MessageKey } from "./messages";

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
  return useMemo(() => (key: MessageKey, values?: Record<string, string | number>) => translate(locale, key, values), [locale]);
}

export function localizePath(path: string, locale: Locale) {
  const [pathname, query = ""] = path.split("?");
  const segments = pathname.split("/").filter(Boolean);
  if (isLocale(segments[0]) || /^[a-z]{2}(?:-[A-Z]{2})?$/.test(segments[0] ?? "")) segments.shift();
  const normalized = segments.length ? `/${segments.join("/")}` : "/";
  const prefix = locale === defaultLocale ? "" : `/${locale}`;
  return `${prefix}${normalized}${query ? `?${query}` : ""}`;
}

export function useLocalizedPath() {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  return (nextLocale: Locale) => {
    const query = searchParams.toString();
    router.push(localizePath(`${pathname}${query ? `?${query}` : ""}`, nextLocale) as never);
  };
}

export { localeLabels, locales };
