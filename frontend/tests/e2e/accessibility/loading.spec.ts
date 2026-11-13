import { expect, test } from "@playwright/test";
import { mockRefreshFailure } from "../fixtures/api";

async function startDelayedCasesNavigation(page: import("@playwright/test").Page) {
  const binding = "11111111111111111111111111111111";
  await page.context().addCookies([
    { name: "finsight_session", value: binding, url: "http://127.0.0.1:3101/", httpOnly: true, sameSite: "Lax" },
    { name: `finsight_access_${binding}`, value: "synthetic-loading", url: "http://127.0.0.1:3101/", httpOnly: true, sameSite: "Lax" }
  ]);
  await page.goto("/graph");
  await page.getByRole("link", { name: "Cases", exact: true }).first().click();
}

test("route loading exposes one accessible status and keeps its skeleton decorative", async ({ page }) => {
  await mockRefreshFailure(page);
  await startDelayedCasesNavigation(page);

  const loadingMain = page.locator("main[aria-busy='true']");
  const status = page.getByRole("status").filter({ hasText: "Loading investigation workspace." });
  await expect(loadingMain).toBeVisible();
  await expect(status).toHaveCount(1);
  await expect(loadingMain).toHaveAttribute("aria-describedby", "workspace-loading-status");
  await expect(loadingMain.locator("[aria-hidden='true']")).toHaveCount(1);
  await expect(loadingMain.locator("[aria-hidden='true']")).toHaveClass(/motion-safe:animate-pulse/);

  await expect(page).toHaveURL(/\/cases$/);
  await expect(page.getByRole("heading", { name: "Investigate and manage cases" })).toBeVisible();
  await expect(status).toHaveCount(0);
});

test("route loading pulse respects reduced-motion preferences", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockRefreshFailure(page);
  await startDelayedCasesNavigation(page);
  const skeleton = page.locator("main[aria-busy='true'] [aria-hidden='true']");
  await expect(skeleton).toBeVisible();
  await expect.poll(() => skeleton.evaluate((element) => getComputedStyle(element).animationName)).toBe("none");
});
