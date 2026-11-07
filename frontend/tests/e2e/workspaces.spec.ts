import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin, mockRefreshFailure } from "./fixtures/api";

async function signInFromCases(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await page.getByRole("button", { name: "Close panel" }).click();
}

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

test("an explicit unknown case URL never falls back and browser history restores the requested selection", async ({ page }) => {
  await mockRefreshFailure(page);
  await page.goto("/cases?case=CASE-UNKNOWN");

  const requested = page.getByRole("region", { name: "Requested case" });
  await expect(requested).toContainText("CASE-UNKNOWN");
  await expect(requested).toContainText("not in the current list");
  await expect(page.getByRole("region", { name: "Selected alert" })).toHaveCount(0);

  await page.getByRole("navigation", { name: "Case navigator" }).getByRole("button", { name: /CASE-1038/ }).click();
  await expect(page).toHaveURL(/case=CASE-1038/);
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-1038");

  await page.getByRole("navigation", { name: "Case navigator" }).getByRole("button", { name: /CASE-1042/ }).click();
  await page.goBack();
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-1038");
  await page.goBack();
  await expect(requested).toContainText("CASE-UNKNOWN");
  await page.goForward();
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-1038");
});

test("an authenticated case absent from the queue resolves through the detail endpoint", async ({ page }) => {
  const archivedCase = { ...liveTransactions[0], id: "CASE-ARCHIVED", merchant: "Archived wire review", notes: [] };
  await mockLogin(page);
  await mockDashboardData(page);
  await page.route("**/api/cases/CASE-ARCHIVED", async (route) => json(route, 200, archivedCase));

  await page.goto("/cases?case=CASE-ARCHIVED");
  await signInFromCases(page);

  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected).toContainText("CASE-ARCHIVED");
  await expect(selected).toContainText("Archived wire review");
});

test("an authenticated unknown case has an explicit not-found state", async ({ page }) => {
  await mockLogin(page);
  await mockDashboardData(page);

  await page.goto("/cases?case=CASE-UNKNOWN");
  await signInFromCases(page);

  const requested = page.getByRole("region", { name: "Requested case" });
  await expect(requested).toContainText("CASE-UNKNOWN");
  await expect(requested.getByRole("alert")).toContainText("not found or is not available");
  await expect(page.getByRole("region", { name: "Selected alert" })).toHaveCount(0);
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

test("a successful upload refreshes the authenticated document library and exposes processing state", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  let documents = [{ id: "document-owned", filename: "statement.pdf", status: "indexed", created_at: "2026-10-01T10:00:00Z" }];
  const authorizations: string[] = [];
  await page.route("**/api/uploads**", async (route) => {
    authorizations.push(route.request().headers().authorization ?? "");
    if (route.request().method() === "POST") {
      documents = [{ id: "new-upload", filename: "new-evidence.pdf", status: "processing", created_at: "2026-10-02T10:00:00Z" }, ...documents];
      return json(route, 200, { file_id: "new-upload", status: "processing", imported: 0, indexed: 0 });
    }
    return json(route, 200, documents);
  });

  await page.goto("/evidence");
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByRole("list", { name: "Documents" }).getByText("statement.pdf")).toBeVisible();
  await page.locator("input[type='file']").setInputFiles({ name: "new-evidence.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") });
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByRole("list", { name: "Documents" }).getByText("new-evidence.pdf")).toBeVisible();
  await expect(page.getByRole("list", { name: "Documents" }).getByText("Processing")).toBeVisible();
  expect(authorizations.length).toBeGreaterThanOrEqual(3);
  expect(authorizations.every((value) => value === "Bearer test-access-token")).toBe(true);
});

test("a failed upload leaves the current document library unchanged", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  let getRequests = 0;
  await page.route("**/api/uploads**", async (route) => {
    if (route.request().method() === "POST") return json(route, 400, { detail: "Unsupported file type" });
    getRequests += 1;
    return json(route, 200, [{ id: "document-owned", filename: "statement.pdf", status: "indexed", created_at: "2026-10-01T10:00:00Z" }]);
  });

  await page.goto("/evidence");
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByRole("list", { name: "Documents" }).getByText("statement.pdf")).toBeVisible();
  await page.locator("input[type='file']").setInputFiles({ name: "bad.pdf", mimeType: "application/pdf", buffer: Buffer.from("invalid") });
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByRole("region", { name: "Upload to Document Library" }).getByRole("alert")).toContainText("Unsupported file type");
  await expect(page.getByRole("list", { name: "Documents" }).getByRole("listitem")).toHaveCount(1);
  expect(getRequests).toBe(1);
});
