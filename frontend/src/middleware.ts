import { NextRequest, NextResponse } from "next/server";
import { defaultLocale, isLocale } from "@/i18n/config";

export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const development = process.env.NODE_ENV === "development";
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  const apiOrigin = apiUrl ? new URL(apiUrl).origin : "";
  const connect = ["'self'", apiOrigin, ...(development ? ["http://localhost:8000", "ws:"] : [])].filter(Boolean).join(" ");
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'"
  ].join("; ");
  const headers = new Headers(request.headers);
  // Overwrite rather than trust client-supplied policy or nonce headers.
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const segments = request.nextUrl.pathname.split("/").filter(Boolean);
  const requestedLocale = segments[0];
  const knownRoutes = new Set(["", "cases", "graph", "evidence", "data", "controls"]);
  const hasLocalePrefix = isLocale(requestedLocale);
  const hasUnknownPrefix = Boolean(requestedLocale && !knownRoutes.has(requestedLocale));
  const locale = hasLocalePrefix ? requestedLocale : defaultLocale;
  headers.set("x-locale", locale);
  const response = hasLocalePrefix || hasUnknownPrefix
    ? NextResponse.rewrite(new URL(`/${segments.slice(1).join("/")}${request.nextUrl.search}`, request.url), { request: { headers } })
    : NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("x-locale", locale);
  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)"]
};
