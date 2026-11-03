import { expect, test } from "@playwright/test";
import { activateControl, analystTokens, json, liveTransactions, mockDashboardData, mockLogin } from "../fixtures/api";

for (const status of [401, 200]) {
  test(`bootstrap HTTP ${status} arriving after login cannot replace the new session`, async ({ page, isMobile }) => {
    let started!: () => void;
    const refreshStarted = new Promise<void>(resolve => { started = resolve; });
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const newToken = "new-login-authoritative-token";
    await mockLogin(page, 200, { ...analystTokens, access_token: newToken });
    await mockDashboardData(page);
    await page.route("**/api/auth/refresh", async route => {
      started();
      await gate;
      await json(route, status, status === 200 ? { ...analystTokens, access_token: "older-bootstrap-token" } : { detail: "Old session expired" });
    });
    try {
      await page.goto("/");
      await refreshStarted;
      await activateControl(page.getByRole("button", { name: "Sign in", exact: true }), isMobile);
      const auth = page.getByRole("region", { name: "Analyst session" });
      await activateControl(auth.locator("form button[type=submit]"), isMobile);
      await expect(page.getByText("Live investigation data is active.")).toBeVisible();
      const response = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/refresh");
      release();
      await response;
      // Wait for the response/UI turn, never for bootstrap before logging in.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await expect(page.getByText("Live investigation data is active.")).toBeVisible();
      await activateControl(page.getByRole("button", { name: "Close panel" }), isMobile);
      const detailRequest = page.waitForRequest(r => new URL(r.url()).pathname === `/api/cases/${liveTransactions[1].id}`);
      const exact = page.getByRole("button", { name: liveTransactions[1].id, exact: true });
      const select = await exact.count() ? exact : page.getByRole("list", { name: "Fraud cases" }).getByRole("button").filter({ hasText: liveTransactions[1].id });
      await activateControl(select, isMobile);
      expect((await detailRequest).headers().authorization).toBe(`Bearer ${newToken}`);
    } finally { release(); }
  });
}
