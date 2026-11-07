import { expect, test } from "@playwright/test";
import { json, mockLogin, mockRefreshFailure } from "./fixtures/api";

test("Triage opens a shareable selected case in the Cases workspace", async ({ page }) => {
  await mockRefreshFailure(page);
  await page.goto("/");
  await page.getByRole("button", { name: "CASE-1038" }).click();
  await page.getByRole("link", { name: "Open case" }).click();
  await expect(page).toHaveURL(/\/cases\?case=CASE-1038/);
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-1038");
  await page.reload();
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-1038");
});

test("Evidence exposes the authenticated document library, global upload, and document Q&A", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await page.route("**/api/uploads**", async (route) => json(route, 200, [{
    id: "document-owned",
    filename: "statement.pdf",
    status: "indexed",
    created_at: "2026-10-01T10:00:00Z"
  }]));

  await page.goto("/evidence");
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();

  await expect(page.getByRole("heading", { name: "Document Library", exact: true })).toBeVisible();
  await expect(page.getByText("statement.pdf").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upload to Document Library" })).toBeVisible();
  await expect(page.getByText("Uploads are stored in your document library, not attached to a case.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Document Q&A" })).toHaveAttribute("aria-pressed", "true");
});

test("Evidence does not present demo documents while signed out", async ({ page }) => {
  await mockRefreshFailure(page);
  await page.goto("/evidence");
  await expect(page.getByText("Demo records are not shown because document access is user-specific.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Documents" })).toHaveCount(0);
});
