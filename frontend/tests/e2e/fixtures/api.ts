import type { Page, Route } from "@playwright/test";

export const analystTokens = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  token_type: "bearer"
};

export const liveTransactions = [
  {
    id: "CASE-9001",
    posted_at: "2026-06-18",
    merchant: "Wire mule cluster",
    description: "New beneficiary received a high-value transfer from an unfamiliar device.",
    amount: "-7400.00",
    currency: "USD",
    category: "New payee",
    source: "model"
  },
  {
    id: "CASE-9002",
    posted_at: "2026-06-17",
    merchant: "Card testing merchant",
    description: "Low-value authorization burst across the same card fingerprint.",
    amount: "-92.13",
    currency: "USD",
    category: "Velocity spike",
    source: "rules"
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
  await page.route("**/api/transactions/summary/**", async (route) => json(route, 200, monthlySummary));
  await page.route("**/api/transactions?limit=50", async (route) => json(route, 200, liveTransactions));
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
