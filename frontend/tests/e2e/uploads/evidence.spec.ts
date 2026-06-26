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

  await page.getByRole("button", { name: "Upload" }).click();

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
  await page.getByRole("button", { name: "Upload" }).click();

  await expect(page.getByText("Unsupported file type")).toBeVisible();
});
