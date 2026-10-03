import { cookies } from "next/headers";
import type { CaseStatus, InvestigationCase } from "@/lib/api";

export type InitialCaseQueue = {
  status: "live" | "unauthenticated" | "unavailable";
  cases: InvestigationCase[] | null;
};

const ACCESS_COOKIE_NAME = "finsight_access_token";

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
  const accessToken = (await cookies()).get(ACCESS_COOKIE_NAME)?.value;
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
