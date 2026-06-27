import { expect, test } from "@playwright/test";
import { analystTokens, json } from "./fixtures/api";

test("renders finance workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Triage live-risk alerts and document decisions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Investigation workspace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Alert queue" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Selected alert" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence summary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decision", exact: true })).toBeVisible();
});

test("changes route from the primary navigation", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop navigation route changes are covered by the desktop project");

  await page.goto("/");
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Cases" }).click();

  await expect(page).toHaveURL(/\/cases$/);
  await expect(page.getByRole("heading", { name: "Review assigned cases and escalation state" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Cases" })).toHaveAttribute(
    "aria-current",
    "page"
  );
});

test("keeps upload controls constrained to supported financial files", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Upload evidence" }).click();

  const fileInput = page.locator("input[type='file']");
  await expect(fileInput).toHaveAttribute("accept", ".csv,.pdf,.png,.jpg,.jpeg");
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toBeDisabled();
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

  await page.route("**/api/auth/login", async (route) => {
    await json(route, 200, analystTokens);
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
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
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Triage" })).toBeVisible();
});
