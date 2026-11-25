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

    await expect(page).toHaveURL(/\/cases\?case=case-001$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Investigate and manage cases" })).toBeVisible();
  });

  test("falls back to English for an unsupported locale prefix", async ({ page }) => {
    await page.goto("/fr/graph");

    await expect(page).toHaveURL(/\/fr\/graph$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Trace connected accounts, devices, and beneficiaries" })).toBeVisible();
  });

  test("normalizes an unsupported locale prefix when switching language", async ({ page }) => {
    await page.goto("/fr/graph?case=case-001");
    await page.locator("#locale-switcher").selectOption("it");

    await expect(page).toHaveURL(/\/it\/graph\?case=case-001$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "it");
  });

  test("keeps the Italian locale when selecting a case", async ({ page }) => {
    await page.goto("/it/cases");
    const navigator = page.getByRole("navigation", { name: "Navigatore dei casi" });
    await navigator.getByRole("button").first().click();

    await expect(page).toHaveURL(/\/it\/cases\?case=/);
    await expect(page.locator("html")).toHaveAttribute("lang", "it");
    await expect(page.getByRole("heading", { name: "Avviso selezionato" })).toBeFocused();
  });

  test("localizes the operational case workflow rather than mixing interface languages", async ({ page }) => {
    await page.goto("/it/cases");

    await expect(page.getByText("Coda dimostrativa. Accedi per caricare i casi in tempo reale.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Accedi", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Chiedi a Copilot" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Carica evidenze" })).toBeVisible();
    await expect(page.getByText("Stato", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Assegnazione", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Esposizione", { exact: true })).toBeVisible();
    await expect(page.getByText("Fonte di rilevamento", { exact: true })).toBeVisible();
    await expect(page.getByText("Accedi per aggiungere note o registrare azioni sul caso.")).toBeVisible();
    await expect(page.getByText("Demo queue. Sign in to load live cases.")).toHaveCount(0);
  });

  test("formats the same currency amount using the active locale", async ({ page }) => {
    await page.goto("/it/");
    const values = await page.evaluate(() => ({
      en: new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(12345.67),
      it: new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(12345.67)
    }));

    expect(values.en).toContain("12,345.67");
    expect(values.it).toContain("12.345,67");
    expect(values.it).toContain("€");
  });
});
