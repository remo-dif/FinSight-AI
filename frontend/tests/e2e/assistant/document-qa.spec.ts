import { expect, test } from "@playwright/test";
import { json, mockDashboardData, mockLogin, mockRefreshFailure } from "../fixtures/api";

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
  await page.goto("/cases");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Document Q&A" }).click();
  await expect(page.getByRole("option", { name: /statement\.pdf · uploaded 2026-10-01 · ID document/ })).toBeVisible();
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
        },
        {
          id: "doc:document-owned:chunk:1",
          document_id: "document-owned",
          document_name: "appendix.pdf",
          chunk_id: "document-owned:1",
          chunk_index: 1,
          page: 2,
          excerpt: "Additional context.",
          reference: "doc:document-owned:chunk:1"
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
  await expect(page.getByText("Question scope")).toBeVisible();
  await expect(page.getByRole("group", { name: "Question scope" }).getByText(/statement\.pdf · uploaded 2026-10-01 · ID document/)).toBeVisible();
  await expect(page.getByText("Cited references")).toBeVisible();
  await expect(page.getByText("Additional retrieved sources (not cited)")).toBeVisible();
  await expect(page.getByText("statement.pdf · chunk 0")).toHaveCount(1);
  await expect(page.getByText("appendix.pdf · chunk 1")).toBeVisible();
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

test("document picker distinguishes duplicate filenames and response scope stays fixed", async ({ page, isMobile }) => {
  test.skip(isMobile, "document assistant interaction is covered in the desktop project");
  await mockLogin(page);
  await mockDashboardData(page);
  let releaseResponse!: () => void;
  const responseBlocked = new Promise<void>((resolve) => { releaseResponse = resolve; });
  await page.route("**/api/uploads**", async (route) => json(route, 200, [
    { id: "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa", filename: "statement.pdf", status: "indexed", created_at: "2026-10-01T10:00:00Z" },
    { id: "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb", filename: "statement.pdf", status: "indexed", created_at: "2026-10-02T10:00:00Z" }
  ]));
  await page.route("**/api/chat", async (route) => {
    await responseBlocked;
    return json(route, 200, {
      session_id: null,
      answer: "Scoped answer.",
      review: "",
      tool_results: {},
      citations: [],
      sources: [],
      grounded: false,
      abstained: true,
      status: "insufficient_evidence",
      grounding_note: "Claim-level support is not verified."
    });
  });

  await page.goto("/cases");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Document Q&A" }).click();

  const selector = page.getByLabel("Select indexed documents");
  await expect(selector.getByRole("option", { name: "statement.pdf · uploaded 2026-10-01 · ID 11111111" })).toBeVisible();
  await expect(selector.getByRole("option", { name: "statement.pdf · uploaded 2026-10-02 · ID 22222222" })).toBeVisible();
  await selector.selectOption("11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
  await page.getByLabel("Ask about selected documents").fill("Use the first statement");
  const request = page.waitForRequest("**/api/chat");
  await page.getByRole("button", { name: "Send message" }).click();
  await request;
  await selector.selectOption("22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb");
  releaseResponse();

  const scope = page.getByRole("group", { name: "Question scope" });
  await expect(scope).toContainText("2026-10-01");
  await expect(scope).toContainText("11111111");
  await expect(scope).not.toContainText("2026-10-02");
  await expect(scope).not.toContainText("22222222");
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
  await page.goto("/cases");
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

test("a newly uploaded indexed document becomes selectable in Document Q&A", async ({ page, isMobile }) => {
  test.skip(isMobile, "document upload and assistant interaction are covered in the desktop project");
  await mockRefreshFailure(page);
  await mockLogin(page);
  let documents: Array<{ id: string; filename: string; status: string; created_at: string }> = [];
  let submittedDocumentIds: unknown;
  await page.route("**/api/uploads**", async (route) => {
    if (route.request().method() === "POST") {
      documents = [{
        id: "new-indexed-document",
        filename: "new-evidence.pdf",
        status: "indexed",
        created_at: "2026-10-03T10:00:00Z"
      }];
      return json(route, 200, { file_id: "new-indexed-document", status: "indexed", imported: 0, indexed: 1 });
    }
    return json(route, 200, documents);
  });
  await page.route("**/api/chat", async (route) => {
    submittedDocumentIds = route.request().postDataJSON().document_ids;
    return json(route, 200, {
      session_id: null,
      answer: "No sufficiently relevant evidence was found.",
      review: "",
      tool_results: {},
      citations: [],
      sources: [],
      grounded: false,
      abstained: true,
      status: "insufficient_evidence",
      grounding_note: "Claim-level support is not verified."
    });
  });

  await page.goto("/evidence");
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await page.locator("input[type='file']").setInputFiles({
    name: "new-evidence.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 synthetic")
  });
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByRole("list", { name: "Documents" }).getByText("new-evidence.pdf")).toBeVisible();
  const selector = page.getByLabel("Select indexed documents");
  await expect(page.getByRole("option", { name: "new-evidence.pdf" })).toBeVisible();
  await selector.selectOption("new-indexed-document");
  await page.getByLabel("Ask about selected documents").fill("What does this document contain?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("No sufficiently relevant document evidence was found.")).toBeVisible();
  expect(submittedDocumentIds).toEqual(["new-indexed-document"]);
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

test("document Q&A keeps scope and long provenance readable on mobile", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile provenance behavior is covered in mobile projects");
  await openDocumentAssistant(page);
  const longDocumentName = `statement-${"x".repeat(120)}.pdf`;
  const longExcerpt = `Evidence-${"y".repeat(240)}`;
  await page.route("**/api/chat", async (route) => json(route, 200, {
    session_id: null,
    answer: "Mobile scoped answer.",
    review: "",
    tool_results: {},
    citations: [{
      id: "long-source",
      document_id: "document-owned",
      document_name: longDocumentName,
      chunk_id: "document-owned:0",
      chunk_index: 0,
      page: 1,
      excerpt: longExcerpt,
      reference: "doc:document-owned:chunk:0"
    }],
    sources: [],
    grounded: false,
    abstained: false,
    status: "ok",
    grounding_note: "References identify retrieved chunks; claim support is not verified."
  }));

  await page.getByLabel("Select indexed documents").selectOption("document-owned");
  await page.getByLabel("Ask about selected documents").fill("Summarize this statement");
  await page.getByRole("button", { name: "Send message" }).click();

  const dialog = page.getByRole("dialog", { name: "Investigation copilot" });
  await expect(dialog.getByRole("group", { name: "Question scope" })).toBeVisible();
  await expect(dialog.getByText(longDocumentName)).toBeVisible();
  await expect(dialog.getByText(longExcerpt)).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
