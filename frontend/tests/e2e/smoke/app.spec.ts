import { expect, test } from "@playwright/test";

const routes = [
  { path: "/", heading: "Triage live-risk alerts and document decisions" },
  { path: "/cases", heading: "Review assigned cases and escalation state" },
  { path: "/graph", heading: "Trace connected accounts, devices, and beneficiaries" },
  { path: "/evidence", heading: "Validate signals before analyst disposition" },
  { path: "/data", heading: "Monitor ingestion quality and investigation data" }
];

test.describe("application smoke", () => {
  for (const route of routes) {
    test(`renders ${route.path}`, async ({ page }) => {
      const consoleErrors: string[] = [];
      await page.route("**/api/auth/refresh", async (request) => request.fulfill({ status: 204 }));
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });

      await page.goto(route.path);

      await expect(page.getByRole("heading", { name: route.heading })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Investigation workspace" })).toBeVisible();
      expect(consoleErrors).toEqual([]);
    });
  }

  test("navigates primary routes without a full page reload", async ({ page, isMobile }) => {
    test.skip(isMobile, "desktop navigation covers route transitions; mobile visibility is covered separately");

    await page.route("**/api/auth/refresh", async (request) => request.fulfill({ status: 204 }));
    await page.goto("/");
    const beforeNavigation = await page.evaluate(() => performance.getEntriesByType("navigation").length);

    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Graph" }).click();

    await expect(page).toHaveURL(/\/graph$/);
    await expect(page.getByRole("heading", { name: "Trace connected accounts, devices, and beneficiaries" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Graph" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const afterNavigation = await page.evaluate(() => performance.getEntriesByType("navigation").length);
    expect(afterNavigation).toBe(beforeNavigation);
  });
});
