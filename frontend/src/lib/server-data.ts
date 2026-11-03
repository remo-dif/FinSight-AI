import { headers } from "next/headers";
import type { CaseStatus, InvestigationCase } from "@/lib/api";

export type InitialCaseQueue = {
  status: "live" | "unauthenticated" | "unavailable";
  cases: InvestigationCase[] | null;
};

function uniqueCookie(raw: string, name: string) {
  const matches = raw.split(";").map(part => part.trim()).filter(part => part.split("=", 1)[0].trim() === name && part.includes("="));
  return matches.length === 1 ? matches[0].slice(matches[0].indexOf("=") + 1).trim() : undefined;
}

function isInvestigationCase(value: unknown): value is InvestigationCase {
  if (!value || typeof value !== "object") return false;
  const caseRecord = value as Record<string, unknown>;
  const transactionFields = ["id", "posted_at", "merchant", "description", "amount", "currency", "category", "source"];
  const validStatus = ["new", "needs_evidence", "escalated", "resolved"].includes(caseRecord.status as CaseStatus);
  return transactionFields.every((field) => typeof caseRecord[field] === "string") &&
    validStatus &&
    (typeof caseRecord.assignee_name === "string" || caseRecord.assignee_name === null) &&
    typeof caseRecord.assigned_to_me === "boolean" &&
    (typeof caseRecord.decision === "string" || caseRecord.decision === null) &&
    (typeof caseRecord.decision_reason === "string" || caseRecord.decision_reason === null) &&
    (typeof caseRecord.updated_at === "string" || caseRecord.updated_at === null);
}

export async function fetchInitialCaseQueue(): Promise<InitialCaseQueue> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host") ?? "";
  const local = process.env.FINSIGHT_LOCAL_HTTP_COOKIES === "true" &&
    process.env.APP_ENV !== "production" && process.env.APP_ENV !== "staging" &&
    /^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host);
  const prefix = local ? "" : "__Host-";
  const rawCookies = requestHeaders.get("cookie") ?? "";
  const binding = uniqueCookie(rawCookies, `${prefix}finsight_session`);
  const accessToken = binding && /^[a-f0-9]{32}$/.test(binding)
    ? uniqueCookie(rawCookies, `${prefix}finsight_access_${binding}`) : undefined;
  if (!accessToken) {
    return { status: "unauthenticated", cases: null };
  }

  const apiOrigin = process.env.API_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_SITE_URL ||
    (process.env.NODE_ENV === "development" ? "http://localhost:8000" : null);
  if (!apiOrigin) {
    return { status: "unavailable", cases: null };
  }

  try {
    const response = await fetch(new URL("/api/cases?limit=50", apiOrigin), {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) {
      return { status: "unavailable", cases: null };
    }

    const payload: unknown = await response.json();
    if (!Array.isArray(payload) || !payload.every(isInvestigationCase)) {
      return { status: "unavailable", cases: null };
    }
    return { status: "live", cases: payload };
  } catch {
    return { status: "unavailable", cases: null };
  }
}
