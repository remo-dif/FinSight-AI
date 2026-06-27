import { expect, test } from "@playwright/test";
import { json, mockDashboardData, mockLogin, mockRefreshFailure } from "../fixtures/api";

test("assistant requests require authentication before live tools run", async ({ page, isMobile }) => {
  test.skip(isMobile, "assistant authentication failure is viewport-independent and covered on desktop");

  await mockRefreshFailure(page);

  await page.goto("/");
  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("Authentication is required before using live finance tools")).toBeVisible();
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

    await page.goto("/");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page
      .getByRole("region", { name: "Analyst session" })
      .locator("form button[type='submit']")
      .click();
    await page.getByRole("button", { name: "Close panel" }).click();
    await page.getByRole("button", { name: "Ask copilot" }).click();
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText(failure.detail)).toBeVisible();
  });
}

test("dashboard API failures show an explicit live-data warning", async ({ page, isMobile }) => {
  test.skip(isMobile, "dashboard API failure behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await page.route("**/api/transactions/summary/**", async (route) =>
    json(route, 500, { detail: "Summary service unavailable" })
  );
  await page.route("**/api/transactions?limit=50", async (route) =>
    json(route, 500, { detail: "Transaction service unavailable" })
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();

  await expect(page.getByText("Showing demo alerts. Sign in when you need live data.")).toBeVisible();
});

test("upload authorization failures are visible to analysts", async ({ page, isMobile }) => {
  test.skip(isMobile, "upload authorization behavior is viewport-independent and covered on desktop");

  await mockLogin(page);
  await mockDashboardData(page);
  await page.route("**/api/uploads", async (route) =>
    json(route, 403, { detail: "Only analysts can upload evidence" })
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();

  await page.getByRole("button", { name: "Close panel" }).click();
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
