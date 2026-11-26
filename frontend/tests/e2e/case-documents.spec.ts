import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin, mockRefreshFailure } from "./fixtures/api";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  if ((page.viewportSize()?.width ?? 1440) < 1024) {
    await page.getByRole("navigation", { name: "Case navigator" }).getByRole("button", { name: /CASE-9001/ }).click();
  }
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-9001");
}

test("an analyst links and removes only an explicitly selected case document", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  const upload = { id: "file-1", filename: "owner-statement.pdf", status: "indexed", created_at: "2026-10-01T10:00:00Z" };
  const linked = { ...upload, content_type: "application/pdf", uploaded_at: upload.created_at, linked_at: "2026-10-02T10:00:00Z", linked_by: "analyst-1", linked_by_name: "Test Analyst" };
  let links: typeof linked[] = [];
  const methods: string[] = [];
  await page.route("**/api/uploads?*", (route) => json(route, 200, [upload]));
  await page.route(/\/api\/cases\/CASE-9001\/documents(?:\/[^/?]+)?$/, async (route) => {
    const method = route.request().method();
    methods.push(method);
    if (method === "POST") {
      expect(route.request().postDataJSON()).toEqual({ uploaded_file_id: upload.id });
      links = [linked];
      return json(route, 201, linked);
    }
    if (method === "DELETE") {
      links = [];
      return route.fulfill({ status: 204 });
    }
    return json(route, 200, links);
  });
  await signIn(page);

  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected.getByText("No documents are linked to this case.")).toBeVisible();
  await selected.getByRole("combobox", { name: "Document from your library" }).selectOption(upload.id);
  await selected.getByRole("button", { name: "Link document" }).click();
  await expect(selected.getByRole("list", { name: "Documents linked to this case" })).toContainText(upload.filename);
  await expect(selected.getByRole("status").filter({ hasText: "Document linked to this case." })).toBeVisible();
  await selected.getByRole("button", { name: `Remove ${upload.filename} from this case` }).click();
  await expect(selected.getByText("No documents are linked to this case.")).toBeVisible();
  expect(methods).toContain("POST");
  expect(methods).toContain("DELETE");
});

test("a failed document list remains an error and retry restores the list", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  let attempts = 0;
  await page.route("**/api/cases/CASE-9001/documents", async (route) => {
    attempts += 1;
    return attempts === 1 ? json(route, 503, { detail: "Unavailable" }) : json(route, 200, []);
  });
  await signIn(page);
  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected.getByRole("alert")).toContainText("Linked documents could not be loaded.");
  await expect(selected.getByText("No documents are linked to this case.")).toHaveCount(0);
  await selected.getByRole("button", { name: "Retry" }).click();
  await expect(selected.getByText("No documents are linked to this case.")).toBeVisible();
});

test("loading is distinct from an empty list and Italian actions stay translated", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  let releaseDocuments: () => void = () => {};
  const documentResponse = new Promise<void>((resolve) => { releaseDocuments = resolve; });
  await page.route("**/api/cases/CASE-9001/documents", async (route) => {
    await documentResponse;
    return json(route, 200, []);
  });
  await signIn(page);
  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected.getByRole("status")).toContainText("Loading linked documents...");
  await expect(selected.getByText("No documents are linked to this case.")).toHaveCount(0);
  releaseDocuments();
  await expect(selected.getByText("No documents are linked to this case.")).toBeVisible();
  await page.getByRole("combobox", { name: "Language" }).selectOption("it");
  await expect(page.getByText("Nessun documento è collegato a questo caso.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Collega documento" })).toBeVisible();
});

test("a closed case shows linked documents without link or remove controls", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  const closed = { ...liveTransactions[0], status: "resolved", decision: "escalate", decision_reason: "Reviewed" };
  await page.route("**/api/cases?limit=50", (route) => json(route, 200, [closed]));
  await page.route("**/api/cases/CASE-9001", (route) => json(route, 200, { ...closed, notes: [], follow_ups: [] }));
  await page.route("**/api/cases/CASE-9001/documents", (route) => json(route, 200, [{
    id: "file-1", filename: "closed-case.pdf", content_type: "application/pdf", status: "indexed",
    uploaded_at: "2026-10-01T10:00:00Z", linked_at: "2026-10-02T10:00:00Z", linked_by: "analyst-1", linked_by_name: "Test Analyst"
  }]));
  await signIn(page);
  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected.getByRole("list", { name: "Documents linked to this case" })).toContainText("closed-case.pdf");
  await expect(selected.getByText("This case is closed. Its document links are read-only.")).toBeVisible();
  await expect(selected.getByRole("button", { name: "Link document" })).toHaveCount(0);
  await expect(selected.getByRole("button", { name: /Remove closed-case.pdf/ })).toHaveCount(0);
});

test("a resolved false positive keeps document linking available", async ({ page }) => {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  const resolved = { ...liveTransactions[0], status: "resolved", decision: "false_positive", decision_reason: "Reviewed" };
  await page.route("**/api/cases?limit=50", (route) => json(route, 200, [resolved]));
  await page.route("**/api/cases/CASE-9001", (route) => json(route, 200, { ...resolved, notes: [], follow_ups: [] }));
  await signIn(page);
  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected.getByRole("button", { name: "Link document" })).toBeVisible();
  await expect(selected.getByText("This case is closed. Its document links are read-only.")).toHaveCount(0);
});
