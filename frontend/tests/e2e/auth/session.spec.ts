import { expect, test } from "@playwright/test";
import {
  analystTokens,
  json,
  mockDashboardData,
  mockLogin,
  mockLogout,
  mockRefreshFailure
} from "../fixtures/api";

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
  const selectedAlert = page.getByRole("region", { name: "Selected alert" });
  await expect(selectedAlert.getByText("CASE-9001", { exact: true })).toBeVisible();
  await expect(selectedAlert).toContainText("Wire mule cluster");

  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(
    page.getByRole("region", { name: "Analyst session" }).getByRole("status")
  ).toContainText("The server confirmed your session was revoked");
  await expect(page.getByText("Sign in to replace demo alerts with live data.")).toBeVisible();
  const stored = await page.evaluate(() => localStorage.getItem("finsight-session"));
  expect(stored).not.toContain(analystTokens.access_token);
});

test("failed logout keeps the session and does not claim that it was revoked", async ({ page, isMobile }) => {
  test.skip(isMobile, "logout behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockRefreshFailure(page);
  await mockDashboardData(page);
  await page.route("**/api/auth/logout", async (route) =>
    json(route, 503, { detail: "Logout temporarily unavailable" })
  );

  await page.goto("/");
  await submitLogin(page);
  await page.getByRole("button", { name: "Sign out" }).click();

  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await expect(authPanel.getByRole("alert")).toContainText("revocation was not confirmed");
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await expect(authPanel.getByRole("status")).toBeHidden();
  await expect(authPanel.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("network failure leaves logout outcome uncertain and offers local-only cleanup", async ({ page, isMobile }) => {
  test.skip(isMobile, "logout behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockRefreshFailure(page);
  await mockDashboardData(page);
  await page.route("**/api/auth/logout", async (route) => route.abort("failed"));

  await page.goto("/");
  await submitLogin(page);
  await page.getByRole("button", { name: "Sign out" }).click();

  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await expect(authPanel.getByRole("alert")).toContainText("outcome is unknown");
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await authPanel.getByRole("button", { name: "Clear this device's session" }).click();
  await expect(authPanel.getByRole("alert")).toContainText("Signed out on this device only");
  await expect(page.getByText("Sign in to replace demo alerts with live data.")).toBeVisible();
});

test("logout timeout is reported as an unknown server outcome", async ({ page, isMobile, browserName }) => {
  test.skip(isMobile, "logout behavior is viewport-independent and covered on desktop");
  test.skip(browserName !== "chromium", "This test accelerates the browser's 10-second timer.");

  await page.addInitScript(() => {
    const originalSetTimeout = window.setTimeout.bind(window);
    window.setTimeout = ((handler: TimerHandler, delay?: number) =>
      originalSetTimeout(handler, delay === 10_000 ? 1 : delay)) as typeof window.setTimeout;
  });
  await mockLogin(page);
  await mockRefreshFailure(page);
  await mockDashboardData(page);
  await page.route("**/api/auth/logout", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 50));
    await json(route, 204, null);
  });

  await page.goto("/");
  await submitLogin(page);
  await page.getByRole("button", { name: "Sign out" }).click();

  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await expect(authPanel.getByRole("alert")).toContainText("timed out");
  await expect(authPanel.getByRole("alert")).toContainText("revocation is unconfirmed");
  await expect(authPanel.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("logout can be retried after a server failure", async ({ page, isMobile }) => {
  test.skip(isMobile, "logout behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockRefreshFailure(page);
  await mockDashboardData(page);
  let attempts = 0;
  await page.route("**/api/auth/logout", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await json(route, 503, { detail: "Logout temporarily unavailable" });
      return;
    }
    await json(route, 204, null);
  });

  await page.goto("/");
  await submitLogin(page);
  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await authPanel.getByRole("button", { name: "Sign out" }).click();
  await expect(authPanel.getByRole("alert")).toContainText("HTTP 503");
  await authPanel.getByRole("button", { name: "Sign out" }).click();

  await expect(authPanel.getByRole("status")).toContainText("server confirmed your session was revoked");
  await expect(page.getByText("Sign in to replace demo alerts with live data.")).toBeVisible();
  expect(attempts).toBe(2);
});

test("reload restores the server session when failed logout leaves its cookie valid", async ({ page, isMobile }) => {
  test.skip(isMobile, "session restoration is viewport-independent and covered on desktop");

  let signedIn = false;
  let refreshCount = 0;
  await page.route("**/api/auth/login", async (route) => {
    signedIn = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(analystTokens)
    });
  });
  await page.route("**/api/auth/refresh", async (route) => {
    refreshCount += 1;
    if (!signedIn) {
      await json(route, 401, { detail: "No refresh session" });
      return;
    }
    await json(route, 200, { ...analystTokens, access_token: "restored-access-token" });
  });
  await page.route("**/api/auth/logout", async (route) =>
    json(route, 503, { detail: "Logout temporarily unavailable" })
  );
  await mockDashboardData(page);

  await page.goto("/");
  await submitLogin(page);
  await page.context().addCookies([{
    name: "finsight_refresh_token",
    value: "test-refresh-token",
    url: "http://127.0.0.1:3101/api/auth/refresh",
    httpOnly: true,
    secure: false,
    sameSite: "Lax"
  }]);
  const hasRefreshCookie = async () =>
    (await page.context().cookies("http://127.0.0.1:3101/api/auth/refresh"))
      .some((cookie) => cookie.name === "finsight_refresh_token");
  expect(await hasRefreshCookie()).toBe(true);
  await page.getByRole("button", { name: "Sign out" }).click();
  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await expect(authPanel.getByRole("alert")).toContainText("HTTP 503");

  await page.reload();

  await expect.poll(() => refreshCount).toBe(2);
  expect(await hasRefreshCookie()).toBe(true);
  await expect(page.getByRole("button", { name: "Session active" })).toBeVisible();
  await page.getByRole("button", { name: "Session active" }).click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("expired refresh session during logout is reported without claiming revocation", async ({ page, isMobile }) => {
  test.skip(isMobile, "logout behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockRefreshFailure(page);
  await mockDashboardData(page);
  let refreshCount = 0;
  await page.route("**/api/auth/refresh", async (route) => {
    refreshCount += 1;
    await json(route, 401, { detail: "Refresh session expired" });
  });
  await page.route("**/api/auth/logout", async (route) =>
    json(route, 401, { detail: "Invalid refresh token" })
  );

  await page.goto("/");
  await submitLogin(page);
  await page.getByRole("button", { name: "Sign out" }).click();

  const authPanel = page.getByRole("region", { name: "Analyst session" });
  await expect(authPanel.getByRole("alert")).toContainText("HTTP 401");
  await expect(authPanel.getByRole("alert")).toContainText("revocation was not confirmed");
  await expect(authPanel.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(refreshCount).toBe(1);
});

test("invalid login reports the API error and keeps demo mode", async ({ page, isMobile }) => {
  test.skip(isMobile, "login error behavior is viewport-independent and covered on desktop");

  await mockLogin(page, 401, { detail: "Invalid email or password" });

  await page.goto("/");
  await submitLogin(page);

  await expect(page.getByText("Invalid email or password")).toBeVisible();
  await expect(page.getByText("Demo queue. Sign in to load live cases.")).toBeVisible();
  await expect(page.getByText("Live investigation data is active.")).toBeHidden();
});

test("secure refresh cookie restores the session after a page reload", async ({ page, isMobile }) => {
  test.skip(isMobile, "session restoration is viewport-independent and covered on desktop");

  let signedIn = false;
  let refreshCount = 0;
  await page.route("**/api/auth/login", async (route) => {
    signedIn = true;
    await json(route, 200, analystTokens);
  });
  await page.route("**/api/auth/refresh", async (route) => {
    refreshCount += 1;
    if (!signedIn) {
      await json(route, 401, { detail: "No refresh session" });
      return;
    }
    await json(route, 200, {
      ...analystTokens,
      access_token: "restored-access-token"
    });
  });
  await mockDashboardData(page);

  await page.goto("/");
  await expect.poll(() => refreshCount).toBe(1);
  await submitLogin(page);
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();

  await page.reload();

  await expect(page.getByText("Live queue is active. Select an alert to review evidence and record a decision.")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Selected alert" }).getByText("CASE-9001", { exact: true })
  ).toBeVisible();
  expect(refreshCount).toBe(2);
  const stored = await page.evaluate(() => localStorage.getItem("finsight-session"));
  expect(stored).not.toContain("restored-access-token");
});

test("expired access token refreshes once and retries live-data requests", async ({ page, isMobile }) => {
  test.skip(isMobile, "token refresh behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  let refreshCount = 0;
  let caseCount = 0;
  await page.route("**/api/auth/refresh", async (route) => {
    refreshCount += 1;
    if (refreshCount === 1) {
      await json(route, 401, { detail: "No refresh session" });
      return;
    }
    await json(route, 200, {
      ...analystTokens,
      access_token: "refreshed-access-token"
    });
  });
  await page.route("**/api/cases?limit=50", async (route) => {
    caseCount += 1;
    if (caseCount === 1) {
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
        source: "model",
        status: "new",
        assignee_name: null,
        assigned_to_me: false,
        decision: null,
        decision_reason: null,
        updated_at: null
      }
    ]);
  });

  await page.goto("/");
  await expect.poll(() => refreshCount).toBe(1);
  await submitLogin(page);

  await expect(
    page.getByRole("region", { name: "Selected alert" }).getByText("CASE-9010", { exact: true })
  ).toBeVisible();
  expect(refreshCount).toBe(2);
});
