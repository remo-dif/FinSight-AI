import { expect, test } from "@playwright/test";
import { mockRefreshFailure } from "../fixtures/api";

test("mobile navigation remains sticky, usable, and horizontally contained while the page scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 });
  await mockRefreshFailure(page);
  await page.goto("/cases");
  await page.addStyleTag({ content: "#dashboard { min-height: 1800px; }" });

  const header = page.locator("header");
  const mobileNavigation = page.getByRole("navigation", { name: "Mobile navigation" });
  const evidenceLink = mobileNavigation.getByRole("link", { name: "Evidence" });
  const initialTop = await header.evaluate((element) => element.getBoundingClientRect().top);

  await expect(mobileNavigation).toBeVisible();
  await expect(evidenceLink).toBeVisible();
  expect(await evidenceLink.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);

  await page.evaluate(() => window.scrollTo(0, 700));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);

  const scrolledTop = await header.evaluate((element) => element.getBoundingClientRect().top);
  expect(Math.abs(scrolledTop - initialTop)).toBeLessThanOrEqual(1);
  await expect(mobileNavigation).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

  await evidenceLink.click();
  await expect(page).toHaveURL(/\/evidence$/);
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
});
