import type { Page, Route } from "@playwright/test";
import type { CaseUpdate, InvestigationCase } from "@/lib/api";

export const analystTokens = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  token_type: "bearer"
};

export const liveTransactions: InvestigationCase[] = [
  {
    id: "CASE-9001",
    posted_at: "2026-06-18",
    merchant: "Wire mule cluster",
    description: "New beneficiary received a high-value transfer from an unfamiliar device.",
    amount: "-7400.00",
    currency: "USD",
    category: "New payee",
    source: "model",
    status: "needs_evidence",
    assignee_name: null,
    assigned_to_me: false,
    decision: null,
    decision_reason: null,
    updated_at: null
  },
  {
    id: "CASE-9002",
    posted_at: "2026-06-17",
    merchant: "Card testing merchant",
    description: "Low-value authorization burst across the same card fingerprint.",
    amount: "-92.13",
    currency: "USD",
    category: "Velocity spike",
    source: "rules",
    status: "new",
    assignee_name: null,
    assigned_to_me: false,
    decision: null,
    decision_reason: null,
    updated_at: null
  }
];

export const monthlySummary = {
  month: "2026-06",
  income: "9200.00",
  spending: "7400.00",
  net_cash_flow: "1800.00"
};

export async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

export async function mockLogin(page: Page, status = 200, body: unknown = analystTokens) {
  await page.route("**/api/auth/login", async (route) => json(route, status, body));
}

export async function mockRefreshFailure(page: Page) {
  await page.route("**/api/auth/refresh", async (route) =>
    json(route, 401, { detail: "Refresh token expired" })
  );
}

export async function mockLogout(page: Page) {
  await page.route("**/api/auth/logout", async (route) => json(route, 204, null));
}

export async function mockDashboardData(page: Page) {
  const cases = liveTransactions.map((caseRecord) => ({ ...caseRecord }));
  const notes = new Map<string, Array<{ id: string; author_name: string; content: string; created_at: string }>>();

  await page.route("**/api/cases?limit=50", async (route) => json(route, 200, cases));
  await page.route(/\/api\/cases\/[^/?]+(?:\/notes)?$/, async (route) => {
    const request = route.request();
    const segments = new URL(request.url()).pathname.split("/").filter(Boolean);
    const caseId = segments[2];
    const caseRecord = cases.find((item) => item.id === caseId);
    if (!caseRecord) {
      await json(route, 404, { detail: "Case not found" });
      return;
    }

    if (request.method() === "PATCH") {
      const update = request.postDataJSON() as CaseUpdate;
      if (update.status) caseRecord.status = update.status;
      if (update.assignee === "me") {
        caseRecord.assignee_name = "Test Analyst";
        caseRecord.assigned_to_me = true;
      } else if (update.assignee === "unassigned") {
        caseRecord.assignee_name = null;
        caseRecord.assigned_to_me = false;
      }
      if (update.decision) {
        caseRecord.decision = update.decision;
        caseRecord.decision_reason = update.reason ?? null;
        caseRecord.status = update.decision === "false_positive"
          ? "resolved"
          : update.decision === "escalate"
            ? "escalated"
            : "needs_evidence";
      }
      caseRecord.updated_at = "2026-10-03T12:00:00.000Z";
      await json(route, 200, caseRecord);
      return;
    }

    if (request.method() === "POST" && segments[3] === "notes") {
      const payload = request.postDataJSON() as { content: string };
      const note = {
        id: `note-${(notes.get(caseId)?.length ?? 0) + 1}`,
        author_name: "Test Analyst",
        content: payload.content,
        created_at: "2026-10-03T12:00:00.000Z"
      };
      notes.set(caseId, [...(notes.get(caseId) ?? []), note]);
      await json(route, 201, note);
      return;
    }

    await json(route, 200, { ...caseRecord, notes: notes.get(caseId) ?? [] });
  });
}

export async function mockChatSuccess(page: Page) {
  await page.route("**/api/chat", async (route) =>
    json(route, 200, {
      session_id: "session-9001",
      answer: "CASE-9001 has new-payee risk, unfamiliar-device evidence, and high exposure.",
      review: "Escalate with reason code NEW_PAYEE_HIGH_VALUE.",
      tool_results: {}
    })
  );
}
