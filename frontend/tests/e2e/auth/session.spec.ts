import { expect, test } from "@playwright/test";
import { analystTokens, json, mockDashboardData, mockLogin, mockLogout } from "../fixtures/api";

async function submitLogin(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
}

test("valid login enables live dashboard data and logout clears the session", async ({ page, isMobile }) => {
  test.skip(isMobile, "session storage behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockDashboardData(page);
  await mockLogout(page);

  await page.goto("/");
  await submitLogin(page);

  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "CASE-9001" })).toBeVisible();
  await expect(page.getByRole("region", { name: "CASE-9001" })).toContainText("Wire mule cluster");

  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page.getByText("Signed out. Demo alerts are visible.")).toBeVisible();
  await expect(page.getByText("Sign in to replace demo alerts with live data.")).toBeVisible();
  const stored = await page.evaluate(() => localStorage.getItem("finsight-session"));
  expect(stored).not.toContain(analystTokens.access_token);
});

test("invalid login reports the API error and keeps demo mode", async ({ page, isMobile }) => {
  test.skip(isMobile, "login error behavior is viewport-independent and covered on desktop");

  await mockLogin(page, 401, { detail: "Invalid email or password" });

  await page.goto("/");
  await submitLogin(page);

  await expect(page.getByText("Invalid email or password")).toBeVisible();
  await expect(page.getByText("Showing demo alerts. Sign in when you need live data.")).toBeVisible();
  await expect(page.getByText("Live investigation data is active.")).toBeHidden();
});

test("expired access token refreshes once and retries live-data requests", async ({ page, isMobile }) => {
  test.skip(isMobile, "token refresh behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  let refreshCount = 0;
  let transactionCount = 0;
  await page.route("**/api/auth/refresh", async (route) => {
    refreshCount += 1;
    await json(route, 200, {
      ...analystTokens,
      access_token: "refreshed-access-token"
    });
  });
  await page.route("**/api/transactions/summary/**", async (route) =>
    json(route, 200, { month: "2026-06", income: "9200.00", spending: "7400.00", net_cash_flow: "1800.00" })
  );
  await page.route("**/api/transactions?limit=50", async (route) => {
    transactionCount += 1;
    if (transactionCount === 1) {
      await json(route, 401, { detail: "Token expired" });
      return;
    }
    await json(route, 200, [
      {
        id: "CASE-9010",
        posted_at: "2026-06-19",
        merchant: "Refresh retry case",
        description: "Retried successfully after access-token refresh.",
        amount: "-1300.00",
        currency: "USD",
        category: "New payee",
        source: "model"
      }
    ]);
  });

  await page.goto("/");
  await submitLogin(page);

  await expect(page.getByRole("heading", { name: "CASE-9010" })).toBeVisible();
  expect(refreshCount).toBe(1);
});
