import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { json, mockDashboardData, mockLogin, mockRefreshFailure } from "./fixtures/api";

async function openAuthenticatedCase(page: import("@playwright/test").Page) {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-9001");
}

test("PDF and exact JSON exports use authenticated requests and safe downloaded names", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/cases/CASE-9001/dossier.*", async (route) => {
    requests.push(`${route.request().method()} ${route.request().headers().authorization} ${route.request().url()}`);
    const format = route.request().url().endsWith(".pdf") ? "pdf" : "json";
    await route.fulfill({
      status: 200,
      contentType: format === "pdf" ? "application/pdf" : "application/json",
      headers: { "Content-Disposition": `attachment; filename="case-CASE-9001-dossier.${format}"`, "X-Dossier-SHA256": "a".repeat(64) },
      body: format === "pdf" ? Buffer.from("%PDF-1.4 synthetic") : Buffer.from('{"a":1,"b":2}')
    });
  });
  await openAuthenticatedCase(page);

  for (const [label, suffix] of [["Export dossier (PDF)", "pdf"], ["Download canonical data (JSON)", "json"]] as const) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: label }).click();
    const saved = await download;
    expect(saved.suggestedFilename()).toBe(`case-CASE-9001-dossier.${suffix}`);
    expect(readFileSync(await saved.path())).toEqual(
      Buffer.from(suffix === "pdf" ? "%PDF-1.4 synthetic" : '{"a":1,"b":2}')
    );
    await expect(page.getByRole("status").filter({ hasText: "Download prepared." })).toBeVisible();
  }
  expect(requests).toHaveLength(2);
  expect(requests.every((item) => item.startsWith("GET Bearer test-access-token") && !item.includes("token="))).toBe(true);
});

test("dossier buttons disable during preparation and report an API error", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/cases/CASE-9001/dossier.pdf", async (route) => {
    await pending;
    await json(route, 503, { detail: "Export unavailable" });
  });
  await openAuthenticatedCase(page);
  await page.getByRole("button", { name: "Export dossier (PDF)" }).click();
  await expect(page.getByRole("button", { name: "Preparing dossier..." })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Download canonical data (JSON)" })).toBeDisabled();
  release();
  await expect(page.getByRole("alert").filter({ hasText: "Export unavailable" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export dossier (PDF)" })).toBeEnabled();
});
