import { expect, test } from "@playwright/test";
import { json, mockDashboardData, mockLogin } from "../fixtures/api";

async function signIn(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await page.getByRole("button", { name: "Close panel" }).click();
}

test("CSV currency selection is explicit, actionable and reset for each file", async ({ page }) => {
  await mockLogin(page);
  await mockDashboardData(page);
  const requests: string[] = [];
  await page.route("**/api/uploads", async (route) => {
    requests.push(route.request().postDataBuffer()?.toString() ?? "");
    if (requests.length === 1) {
      return json(route, 400, { detail: "Missing currency on CSV line 2. Add a currency column or select the statement currency, then retry the entire import." });
    }
    return json(route, 200, { file_id: "synthetic-upload", status: "processed", imported: 1, indexed: 0 });
  });
  await page.goto("/");
  await signIn(page);
  await page.getByRole("button", { name: "Upload evidence" }).click();
  const input = page.locator("input[type='file']");
  await input.setInputFiles({ name: "statement.csv", mimeType: "text/csv", buffer: Buffer.from("date,merchant,amount\n2025-01-01,Synthetic,-1.20\n") });
  const selector = page.getByLabel("CSV currency", { exact: true });
  await expect(selector).toHaveValue("");
  await expect(selector.locator("option:checked")).toHaveText("Use currency column");
  await expect(page.getByText(/If your CSV has no currency column/)).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByRole("region", { name: "Evidence ingestion" }).getByRole("alert")).toContainText("select the statement currency");
  expect(requests[0]).not.toContain('name="import_currency"');
  await selector.selectOption("EUR");
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText("processed: 1 imported, 0 indexed")).toBeVisible();
  expect(requests[1]).toMatch(/name="import_currency"\r\n\r\nEUR/);
  await input.setInputFiles({ name: "another.csv", mimeType: "text/csv", buffer: Buffer.from("date,merchant,amount,currency\n2025-01-01,Synthetic,-1.20,USD\n") });
  await expect(selector).toHaveValue("");
  await input.setInputFiles({ name: "document.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") });
  await expect(selector).toHaveCount(0);
});

test("uploads accepted evidence files and reports processing counts", async ({ page, isMobile }) => {
  test.skip(isMobile, "upload mutation behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockDashboardData(page);
  await page.route("**/api/uploads", async (route) =>
    json(route, 200, {
      file_id: "upload-123",
      status: "processed",
      imported: 12,
      indexed: 7
    })
  );

  await page.goto("/");
  await signIn(page);
  await page.getByRole("button", { name: "Upload evidence" }).click();

  await page.locator("input[type='file']").setInputFiles({
    name: "evidence.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("posted_at,merchant,amount\n2026-06-20,Merchant,-10.00\n")
  });
  await expect(page.getByText("evidence.csv")).toBeVisible();

  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByText("processed: 12 imported, 7 indexed")).toBeVisible();
});

test("rejected evidence files surface backend validation messages", async ({ page, isMobile }) => {
  test.skip(isMobile, "upload validation behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockDashboardData(page);
  await page.route("**/api/uploads", async (route) =>
    json(route, 400, { detail: "Unsupported file type" })
  );

  await page.goto("/");
  await signIn(page);
  await page.getByRole("button", { name: "Upload evidence" }).click();

  await page.locator("input[type='file']").setInputFiles({
    name: "malware.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("not a supported evidence file")
  });
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByText("Unsupported file type")).toBeVisible();
});
