import { expect, test } from "@playwright/test";

test("renders finance workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Investigate suspicious transaction activity" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Investigation copilot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence ingestion" })).toBeVisible();
});

test("keeps upload controls constrained to supported financial files", async ({ page }) => {
  await page.goto("/");

  const fileInput = page.locator("input[type='file']");
  await expect(fileInput).toHaveAttribute("accept", ".csv,.pdf,.png,.jpg,.jpeg");
  await expect(page.getByRole("button", { name: "Upload" })).toBeDisabled();
  await expect(page.getByText("Files are validated before processing.")).toBeVisible();
});

test("sets baseline browser security headers", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response?.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  expect(response?.headers()["x-powered-by"]).toBeUndefined();
});

test("does not persist bearer tokens after analyst sign in", async ({ page, isMobile }) => {
  test.skip(isMobile, "token persistence behavior is viewport-independent and covered on desktop");

  await page.route("http://localhost:8000/api/auth/login", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "test-access-token",
        refresh_token: "test-refresh-token",
        token_type: "bearer"
      })
    });
  });

  await page.goto("/");
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();

  const stored = await page.evaluate(() => localStorage.getItem("finsight-session"));
  expect(stored).not.toContain("test-access-token");
  expect(stored).not.toContain("test-refresh-token");
});

test("keeps primary navigation reachable on mobile", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile navigation is covered by the mobile project");

  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Triage" })).toBeVisible();
});
