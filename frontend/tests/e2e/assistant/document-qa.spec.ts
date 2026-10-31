import { expect, test } from "@playwright/test";
import { json, mockDashboardData, mockLogin } from "../fixtures/api";

async function openDocumentAssistant(page: import("@playwright/test").Page) {
  await mockLogin(page);
  await mockDashboardData(page);
  const uploadsAuthorization: string[] = [];
  await page.route("**/api/uploads**", async (route) => {
    uploadsAuthorization.push(route.request().headers().authorization ?? "");
    await json(route, 200, [
      {
        id: "document-owned",
        filename: "statement.pdf",
        status: "indexed",
        created_at: "2026-10-01T10:00:00Z"
      },
      {
        id: "document-unindexed",
        filename: "not-indexed.csv",
        status: "processed",
        created_at: "2026-10-02T10:00:00Z"
      }
    ]);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Document Q&A" }).click();
  await expect(page.getByRole("option", { name: "statement.pdf" })).toBeVisible();
  await expect(page.getByRole("option", { name: "not-indexed.csv" })).toHaveCount(0);
  return uploadsAuthorization;
}

test("document Q&A sends authenticated selected scope and renders citations as text", async ({ page, isMobile }) => {
  test.skip(isMobile, "document assistant interaction is covered in the desktop project");
  const uploadsAuthorization = await openDocumentAssistant(page);

  let requestBody: Record<string, unknown> | undefined;
  let authorization: string | undefined;
  await page.route("**/api/chat", async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    authorization = route.request().headers().authorization;
    await json(route, 200, {
      session_id: null,
      answer: "Revenue was 50. <script>window.injected = true</script>",
      review: "",
      tool_results: {},
      citations: [
        {
          id: "doc:document-owned:chunk:0",
          document_id: "document-owned",
          document_name: "statement.pdf",
          chunk_id: "document-owned:0",
          chunk_index: 0,
          page: null,
          excerpt: "Revenue was 50.",
          reference: "doc:document-owned:chunk:0"
        }
      ],
      sources: [
        {
          id: "doc:document-owned:chunk:0",
          document_id: "document-owned",
          document_name: "statement.pdf",
          chunk_id: "document-owned:0",
          chunk_index: 0,
          page: null,
          excerpt: "Revenue was 50.",
          reference: "doc:document-owned:chunk:0"
        }
      ],
      grounded: false,
      abstained: false,
      status: "ok",
      grounding_note: "References identify retrieved chunks; claim support is not verified."
    });
  });
  await page.getByLabel("Select indexed documents").selectOption("document-owned");
  await page.getByLabel("Ask about selected documents").fill("What is the revenue?");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("References validated; claim-level support is not verified.")).toBeVisible();
  await expect(page.getByText("Cited references")).toBeVisible();
  await expect(page.getByText("statement.pdf · chunk 0")).toHaveCount(2);
  await expect(page.getByText("Revenue was 50. <script>window.injected = true</script>")).toBeVisible();
  expect(requestBody).toMatchObject({
    message: "What is the revenue?",
    mode: "document_qa",
    document_ids: ["document-owned"]
  });
  expect(authorization).toBe("Bearer test-access-token");
  expect(uploadsAuthorization).toContain("Bearer test-access-token");
  expect(await page.evaluate(() => (window as Window & { injected?: boolean }).injected)).toBeUndefined();
});

test("document picker loads bounded pages without losing the selected scope", async ({ page, isMobile }) => {
  test.skip(isMobile, "document assistant interaction is covered in the desktop project");
  await mockLogin(page);
  await mockDashboardData(page);
  const offsets: string[] = [];
  await page.route("**/api/uploads**", async (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset"));
    offsets.push(String(offset));
    const documents = offset === 0
      ? Array.from({ length: 100 }, (_, index) => ({
          id: `document-${index}`,
          filename: `statement-${index}.pdf`,
          status: "indexed",
          created_at: "2026-10-01T10:00:00Z"
        }))
      : [{
          id: "document-last-page",
          filename: "final-statement.pdf",
          status: "indexed",
          created_at: "2026-10-02T10:00:00Z"
        }];
    await json(route, 200, documents);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Document Q&A" }).click();
  const selector = page.getByLabel("Select indexed documents");
  await expect(page.getByRole("option", { name: "statement-0.pdf" })).toBeVisible();
  await selector.selectOption("document-0");
  await page.getByRole("button", { name: "Load more documents" }).click();
  await expect(page.getByRole("option", { name: "final-statement.pdf" })).toBeVisible();
  expect(await selector.inputValue()).toBe("document-0");
  expect(offsets).toEqual(["0", "100"]);
});

test("document Q&A exposes abstention and provider failure statuses", async ({ page, isMobile }) => {
  test.skip(isMobile, "document assistant interaction is covered in the desktop project");
  await openDocumentAssistant(page);

  let count = 0;
  await page.route("**/api/chat", async (route) => {
    count += 1;
    const abstained = count === 1;
    await json(route, 200, {
      session_id: null,
      answer: abstained
        ? "I could not find enough relevant evidence."
        : "Document Q&A is temporarily unavailable.",
      review: "",
      tool_results: {},
      citations: [],
      sources: [],
      grounded: false,
      abstained: true,
      status: abstained ? "insufficient_evidence" : "provider_error",
      grounding_note: "Claim-level support is not verified."
    });
  });
  await page.getByLabel("Select indexed documents").selectOption("document-owned");
  await page.getByLabel("Ask about selected documents").fill("Question one");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("No sufficiently relevant document evidence was found.")).toBeVisible();
  await page.getByLabel("Ask about selected documents").fill("Question two");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Document Q&A provider error.")).toBeVisible();
});
