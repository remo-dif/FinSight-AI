import { expect, test } from "@playwright/test";

const routes = [
  { path: "/", heading: "Triage alerts that need attention", workspace: "Triage workspace" },
  { path: "/cases", heading: "Investigate and manage cases", workspace: "Case investigation" },
  { path: "/graph", heading: "Trace connected accounts, devices, and beneficiaries", comingSoon: true },
  { path: "/evidence", heading: "Examine your document library", workspace: "Document workspace" },
  { path: "/data", heading: "Monitor investigation data and ingestion quality", comingSoon: true },
  { path: "/controls", heading: "Configure operational controls and policies", comingSoon: true }
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
      if (route.comingSoon) {
        await expect(page.getByRole("heading", { name: "This workspace is not available yet" })).toBeVisible();
        await expect(page.getByRole("link", { name: "Return to Triage" })).toBeVisible();
      } else {
        await expect(page.getByRole("heading", { name: route.workspace })).toBeVisible();
      }
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
    await expect(page.getByRole("heading", { name: "This workspace is not available yet" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Graph" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const afterNavigation = await page.evaluate(() => performance.getEntriesByType("navigation").length);
    expect(afterNavigation).toBe(beforeNavigation);
  });
});
