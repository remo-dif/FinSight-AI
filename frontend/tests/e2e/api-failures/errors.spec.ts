import { expect, test } from "@playwright/test";
import { json, mockDashboardData, mockLogin, mockRefreshFailure } from "../fixtures/api";

test("Cases hides the copilot for signed-out users", async ({ page }) => {
  await mockRefreshFailure(page);

  await page.goto("/cases");
  await expect(page.getByRole("link", { name: "Sign in", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask copilot" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Investigation copilot" })).toHaveCount(0);
});

const chatFailures = [
  { status: 404, detail: "Chat session was not found" },
  { status: 429, detail: "Too many assistant requests. Try again later." },
  { status: 500, detail: "Assistant service unavailable" }
];

for (const failure of chatFailures) {
  test(`assistant surfaces ${failure.status} API failures`, async ({ page, isMobile }) => {
    test.skip(isMobile, "assistant API failure behavior is viewport-independent and covered on desktop");

    await mockLogin(page);
    await mockDashboardData(page);
    await page.route("**/api/chat", async (route) =>
      json(route, failure.status, { detail: failure.detail })
    );

    await page.goto("/cases");
    await page.getByRole("link", { name: "Sign in" }).click();
    await page
      .getByRole("region", { name: "Analyst session" })
      .locator("form button[type='submit']")
      .click();
    await page.getByRole("button", { name: "Ask copilot" }).click();
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText(failure.detail)).toBeVisible();
  });
}

test("dashboard API failures do not fall back to demo cases for an authenticated analyst", async ({ page, isMobile }) => {
  test.skip(isMobile, "dashboard API failure behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await page.route("**/api/cases?limit=50", async (route) =>
    json(route, 500, { detail: "Case service unavailable" })
  );

  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();

  await expect(page.getByText("Live cases are unavailable. No demo cases are shown.")).toBeVisible();
  await expect(page.getByText("Cases are unavailable.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "CASE-1042" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Case navigator" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Cases are unavailable." }).getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask copilot" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Upload evidence" })).toHaveCount(0);
});

test("case queue distinguishes loading and empty live states", async ({ page }) => {
  await mockLogin(page);
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/cases?limit=50", async (route) => {
    await blocked;
    await json(route, 200, []);
  });

  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  const loadingAnnouncement = page.getByRole("status").filter({ hasText: "Loading cases..." });
  await expect(loadingAnnouncement).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(1);

  release();
  const emptyAnnouncement = page.getByRole("status").filter({ hasText: "No cases need attention" });
  await expect(emptyAnnouncement).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(1);
  await expect(page.getByText("No case selected")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Case navigator" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask copilot" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Upload evidence" })).toHaveCount(0);
  await expect(page.getByRole("table")).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Fraud cases" })).toHaveCount(0);

  await page.getByRole("link", { name: "Triage", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No alerts need triage" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Next investigation" })).toHaveCount(0);
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("failed refresh keeps previously loaded cases available", async ({ page, isMobile }) => {
  test.skip(isMobile, "cached refresh behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  let requestCount = 0;
  await page.route("**/api/cases?limit=50", async (route) => {
    requestCount += 1;
    if (requestCount === 1) {
      await json(route, 200, [
        {
          id: "CASE-CACHED",
          posted_at: "2026-11-07",
          merchant: "Cached case",
          description: "Previously loaded investigation case",
          amount: "-10.00",
          currency: "USD",
          category: "Review",
          source: "rules",
          status: "new",
          assignee_name: null,
          assigned_to_me: false,
          decision: null,
          decision_reason: null,
          updated_at: null
        }
      ]);
      return;
    }
    await json(route, 503, { detail: "Temporary refresh failure" });
  });
  await page.route("**/api/cases/CASE-CACHED", async (route) => {
    await json(route, 200, {
      id: "CASE-CACHED",
      posted_at: "2026-11-07",
      merchant: "Cached case",
      description: "Previously loaded investigation case",
      amount: "-10.00",
      currency: "USD",
      category: "Review",
      source: "rules",
      status: "new",
      assignee_name: route.request().method() === "PATCH" ? "Test Analyst" : null,
      assigned_to_me: route.request().method() === "PATCH",
      decision: null,
      decision_reason: null,
      updated_at: null,
      notes: []
    });
  });

  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByRole("button", { name: "CASE-CACHED" })).toBeVisible();

  await page.getByRole("button", { name: "Assign to me" }).click();
  await expect(page.getByText("Refresh failed. Showing the most recently loaded cases.")).toBeVisible();
  await expect(page.getByRole("button", { name: "CASE-CACHED" })).toBeVisible();
});

test("cases page renders an authenticated data failure without demo records", async ({ page, isMobile }) => {
  test.skip(isMobile, "server-rendered case queue behavior is viewport-independent and covered on desktop");

  await page.context().addCookies([
    { name: "finsight_session", value: "11111111111111111111111111111111", url: "http://127.0.0.1:3101/", httpOnly: true, sameSite: "Lax" },
    {
      name: "finsight_access_11111111111111111111111111111111",
      value: "expired-access-token",
      url: "http://127.0.0.1:3101/",
      httpOnly: true,
      sameSite: "Lax"
    }
  ]);

  await page.goto("/cases");

  await expect(page.getByText("Live cases are unavailable. No demo cases are shown.")).toBeVisible();
  await expect(page.getByRole("button", { name: "CASE-1042" })).toHaveCount(0);
});

test("upload authorization failures are visible to analysts", async ({ page, isMobile }) => {
  test.skip(isMobile, "upload authorization behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockDashboardData(page);
  await page.route("**/api/uploads", async (route) =>
    json(route, 403, { detail: "Only analysts can upload evidence" })
  );

  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await page.getByRole("button", { name: "Upload evidence" }).click();
  const fileInput = page.locator("input[type='file']");
  await fileInput.setInputFiles({
    name: "statement.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("posted_at,merchant,amount\n2026-06-20,Test,-10.00\n")
  });
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByText("Only analysts can upload evidence")).toBeVisible();
});


test("SSR rejects duplicate session selectors before choosing a cookie", async ({ request }) => {
  const binding = "11111111111111111111111111111111";
  const single = await request.get("/cases", {
    headers: { Cookie: `finsight_session=${binding}; finsight_access_${binding}=expired-access-token` }
  });
  expect(await single.text()).toContain("Live cases are unavailable. No demo cases are shown.");
  const response = await request.get("/cases", {
    headers: {
      Cookie: `finsight_session=${binding}; finsight_session=${binding}; finsight_access_${binding}=expired-access-token`
    }
  });
  expect(response.ok()).toBe(true);
  expect(await response.text()).not.toContain("Live cases are unavailable. No demo cases are shown.");
});
