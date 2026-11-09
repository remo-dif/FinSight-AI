import { expect, test } from "@playwright/test";
import { analystTokens, json, liveTransactions } from "../fixtures/api";

const aDocument = { id: "synthetic-a-document", filename: "private-a.pdf", status: "indexed", created_at: "2026-06-18" };
const bDocument = { ...aDocument, id: "synthetic-b-document", filename: "private-b.pdf" };

function gate() {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  return { wait, release };
}

test("failed refresh drops A's SSR data, documents and transcript before B signs in", async ({ page }) => {
  const bQueue = gate();
  const bDocuments = gate();
  const delayed = gate();
  const bQueueStarted = gate();
  let refreshes = 0;
  const binding = "11111111111111111111111111111111";
  await page.context().addCookies([
    { name: "finsight_session", value: binding, url: "http://127.0.0.1:3101", httpOnly: true },
    { name: `finsight_access_${binding}`, value: "synthetic-a", url: "http://127.0.0.1:3101", httpOnly: true }
  ]);
  await page.route("**/api/auth/refresh", (route) => ++refreshes === 1
    ? json(route, 200, { ...analystTokens, access_token: "synthetic-a" })
    : json(route, 401, { detail: "Synthetic expiration" }));
  await page.route("**/api/auth/login", (route) => json(route, 200, { ...analystTokens, access_token: "synthetic-b" }));
  await page.route("**/api/cases?limit=50", async (route) => {
    if (route.request().headers().authorization === "Bearer synthetic-b") {
      bQueueStarted.release();
      await bQueue.wait;
      return json(route, 200, [{ ...liveTransactions[0], id: "CASE-B-ONLY" }]);
    }
    return json(route, 200, [{ ...liveTransactions[0], id: "CASE-LIVE-A" }]);
  });
  await page.route(/\/api\/cases\/[^/?]+$/, (route) => json(route, 404, { detail: "Synthetic case" }));
  await page.route("**/api/uploads?**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().headers().authorization === "Bearer synthetic-b") {
      await bDocuments.wait;
      return json(route, 200, [bDocument]);
    }
    if (url.searchParams.get("offset") !== "0") return json(route, 401, {});
    return json(route, 200, [aDocument, ...Array.from({ length: 99 }, (_, i) => ({
      ...aDocument, id: `unindexed-${i}`, status: "processed"
    }))]);
  });
  await page.route("**/api/chat", async (route) => {
    const isDelayed = route.request().postDataJSON().message === "Delayed A question";
    if (isDelayed) await delayed.wait;
    const isB = route.request().headers().authorization === "Bearer synthetic-b";
    if (isB) expect(route.request().postDataJSON().document_ids).toEqual([bDocument.id]);
    await json(route, 200, {
      session_id: null, answer: isB ? "Private answer B" : isDelayed ? "Delayed private answer A" : "Private answer A",
      status: "ok", citations: [], sources: []
    });
  });

  try {
    const response = await page.goto("/cases");
    expect(await response?.text()).toContain("CASE-SSR-A");
    const aCase = page.getByRole("button", { name: /CASE-LIVE-A/ }).first();
    await expect(aCase).toBeVisible();
    await aCase.click();
    await expect(page).toHaveURL(/case=CASE-LIVE-A/);
    await page.getByRole("button", { name: "Ask copilot" }).click();
    await page.getByRole("button", { name: "Document Q&A" }).click();
    const picker = page.getByLabel("Select indexed documents");
    await picker.selectOption(aDocument.id);
    await page.getByLabel("Ask about selected documents").fill("First A question");
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByText("Private answer A", { exact: true })).toBeVisible();
    await page.getByLabel("Ask about selected documents").fill("Delayed A question");
    const request = page.waitForRequest("**/api/chat");
    await page.getByRole("button", { name: "Send message" }).click();
    await request;
    await page.getByRole("button", { name: "Load more documents" }).click();
    await expect(page.getByText("Sign in to select your uploaded documents.")).toBeVisible();
    await expect.soft(page.getByText("Private answer A", { exact: true })).toHaveCount(0, { timeout: 1500 });

    await page.getByRole("button", { name: "Close panel" }).click();
    // Accept either label so a stale SSR shell does not prevent the B login probe.
    await page.getByRole("button", { name: /^(Sign in|Session active)$/ }).click();
    const auth = page.getByRole("region", { name: "Analyst session" });
    await auth.getByLabel("Email").fill("synthetic-b@example.test");
    await auth.getByLabel("Password").fill("synthetic-password-only");
    await auth.locator("form button[type='submit']").click();
    await bQueueStarted.wait;
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect.soft(page.getByText("CASE-SSR-A", { exact: true })).toHaveCount(0, { timeout: 1500 });
    await expect(page.getByText("CASE-LIVE-A", { exact: true })).toHaveCount(0);
    bQueue.release();
    await expect(page.getByRole("button", { name: /CASE-B-ONLY/ }).first()).toBeVisible();
    await page.getByRole("button", { name: "Ask copilot" }).click();
    await page.getByRole("button", { name: "Document Q&A" }).click();
    await expect(page.getByText("private-a.pdf", { exact: false })).toHaveCount(0);
    bDocuments.release();
    await expect(picker.getByRole("option", { name: /private-b.pdf/ })).toBeVisible();
    await expect(picker).toHaveValues([]);
    const staleResponse = page.waitForResponse((response) => response.url().endsWith("/api/chat") &&
      response.request().postDataJSON().message === "Delayed A question");
    delayed.release();
    await (await staleResponse).finished();
    await picker.selectOption(bDocument.id);
    await page.getByLabel("Ask about selected documents").fill("B question");
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByText("Private answer B", { exact: true })).toBeVisible();
    await expect(page.getByText(/Private answer A|Delayed private answer A|Delayed A question/)).toHaveCount(0);
  } finally {
    bQueue.release();
    bDocuments.release();
    delayed.release();
  }
});

test("same-session token rotation retains the document selection and transcript", async ({ page }) => {
  let refreshes = 0;
  let chats = 0;
  await page.route("**/api/auth/refresh", (route) => json(route, 200, {
    ...analystTokens, access_token: ++refreshes === 1 ? "synthetic-a" : "synthetic-a-rotated"
  }));
  await page.route("**/api/uploads?**", (route) => json(route, 200, [aDocument]));
  await page.route("**/api/chat", (route) => {
    chats++;
    if (chats === 2) return json(route, 401, {});
    return json(route, 200, { session_id: null, answer: `Synthetic answer ${chats}`, status: "ok", citations: [], sources: [] });
  });
  await page.goto("/evidence");
  const picker = page.getByLabel("Select indexed documents");
  await picker.selectOption(aDocument.id);
  for (const answer of [1, 3]) {
    await page.getByLabel("Ask about selected documents").fill(`Synthetic question ${answer}`);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByText(`Synthetic answer ${answer}`, { exact: true })).toBeVisible();
  }
  expect(refreshes).toBe(2);
  await expect(picker).toHaveValues([aDocument.id]);
  await expect(page.getByText("Synthetic answer 1", { exact: true })).toBeVisible();
});


test("B resolves the same case link without exposing A's delayed detail", async ({ page }) => {
  const aDetail = gate();
  const aDetailStarted = gate();
  const bDetail = gate();
  const bDetailStarted = gate();
  let refreshes = 0;
  const detailPath = "**/api/cases/CASE-SHARED";
  await page.route("**/api/auth/refresh", (route) => ++refreshes === 1
    ? json(route, 200, { ...analystTokens, access_token: "synthetic-a" })
    : json(route, 401, { detail: "Synthetic expiration" }));
  await page.route("**/api/auth/login", (route) => json(route, 200, { ...analystTokens, access_token: "synthetic-b" }));
  await page.route("**/api/cases?limit=50", (route) => json(route, 200, []));
  await page.route(detailPath, async (route) => {
    const bearer = route.request().headers().authorization;
    if (bearer === "Bearer synthetic-a") {
      aDetailStarted.release();
      await aDetail.wait;
      return json(route, 200, { ...liveTransactions[0], id: "CASE-SHARED", merchant: "A private case detail", notes: [] });
    }
    expect(bearer).toBe("Bearer synthetic-b");
    bDetailStarted.release();
    await bDetail.wait;
    return json(route, 200, { ...liveTransactions[0], id: "CASE-SHARED", merchant: "B authorized case detail", notes: [] });
  });
  await page.route("**/api/uploads?**", (route) => {
    const offset = new URL(route.request().url()).searchParams.get("offset");
    return offset === "0"
      ? json(route, 200, Array.from({ length: 100 }, (_, i) => ({ ...aDocument, id: `indexed-${i}` })))
      : json(route, 401, {});
  });

  try {
    await page.goto("/cases?case=CASE-SHARED");
    await aDetailStarted.wait;
    await page.getByRole("button", { name: "Ask copilot" }).click();
    await page.getByRole("button", { name: "Document Q&A" }).click();
    await page.getByRole("button", { name: "Load more documents" }).click();
    await expect(page.getByText("Sign in to select your uploaded documents.")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    const auth = page.getByRole("region", { name: "Analyst session" });
    await auth.getByLabel("Email").fill("synthetic-b@example.test");
    await auth.getByLabel("Password").fill("synthetic-password-only");
    await auth.locator("form button[type='submit']").click();
    await bDetailStarted.wait;
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page).toHaveURL(/case=CASE-SHARED/);
    const staleResponse = page.waitForResponse((response) => response.url().endsWith("/api/cases/CASE-SHARED") &&
      response.request().headers().authorization === "Bearer synthetic-a");
    aDetail.release();
    await (await staleResponse).finished();
    await expect(page.getByRole("region", { name: "Requested case" })).toBeVisible();
    await expect(page.getByText("A private case detail", { exact: true })).toHaveCount(0);
    bDetail.release();
    await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("B authorized case detail");
    await expect(page.getByText("A private case detail", { exact: true })).toHaveCount(0);
  } finally {
    aDetail.release();
    bDetail.release();
  }
});
