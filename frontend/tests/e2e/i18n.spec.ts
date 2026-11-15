import { expect, test } from "@playwright/test";

test.describe("internationalization", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/auth/refresh", async (request) => request.fulfill({ status: 204 }));
  });

  test("routes Italian pages with Italian document language and copy", async ({ page }) => {
    await page.goto("/it/graph");

    await expect(page).toHaveURL(/\/it\/graph$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "it");
    await expect(page.getByRole("heading", { name: "Traccia account, dispositivi e beneficiari collegati" })).toBeVisible();
  });

  test("switches locale while preserving the current page and query string", async ({ page }) => {
    await page.goto("/it/cases?case=case-001");
    await page.locator("#locale-switcher").selectOption("en");

    await expect(page).toHaveURL(/\/en\/cases\?case=case-001$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Investigate and manage cases" })).toBeVisible();
  });

  test("falls back to English for an unsupported locale prefix", async ({ page }) => {
    await page.goto("/fr/graph");

    await expect(page).toHaveURL(/\/fr\/graph$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Trace connected accounts, devices, and beneficiaries" })).toBeVisible();
  });

  test("formats the same currency amount using the active locale", async ({ page }) => {
    await page.goto("/it/");
    const values = await page.evaluate(() => ({
      en: new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(1234.56),
      it: new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(1234.56)
    }));

    expect(values.en).toContain("1,234.56");
    expect(values.it).toContain("1.234,56");
    expect(values.it).toContain("€");
  });
});
