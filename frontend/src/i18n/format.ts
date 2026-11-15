import type { Locale } from "./config";

export function formatDate(value: Date | string | number, locale: Locale, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat(locale === "it" ? "it-IT" : "en-US", options).format(new Date(value));
}

export function formatNumber(value: number, locale: Locale, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(locale === "it" ? "it-IT" : "en-US", options).format(value);
}

export function formatCurrency(value: number, currency: string, locale: Locale) {
  return new Intl.NumberFormat(locale === "it" ? "it-IT" : "en-US", { style: "currency", currency }).format(value);
}
