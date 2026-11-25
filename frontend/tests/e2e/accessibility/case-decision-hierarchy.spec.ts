import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockLogin, mockRefreshFailure } from "../fixtures/api";

const weakHighExposure = {
  ...liveTransactions[0],
  id: "CASE-HIGH-EXPOSURE-WEAK-SIGNAL",
  merchant: "High exposure routine transfer with an intentionally long merchant name",
  amount: "-9500000.25",
  category: "Routine review",
  description: "A large transfer selected for routine review without a confirmed elevated-risk signal.",
  status: "new" as const,
  assignee_name: null
};

const strongLowExposure = {
  ...liveTransactions[1],
  id: "CASE-LOW-EXPOSURE-STRONG-SIGNAL",
  merchant: "Rapid authorization cluster",
  amount: "-1.25",
  category: "Velocity spike",
  description: "A first-seen device attempted repeated authorizations in a short interval.",
  status: "escalated" as const,
  assignee_name: "Risk Operations"
};

async function openLiveCases(page: import("@playwright/test").Page) {
  await mockRefreshFailure(page);
  await mockLogin(page);
  await page.route("**/api/cases?limit=50", (route) => json(route, 200, [weakHighExposure, strongLowExposure]));
  await page.route(/\/api\/cases\/CASE-(?:HIGH|LOW)-EXPOSURE-/, (route) => {
    const record = route.request().url().includes("HIGH") ? weakHighExposure : strongLowExposure;
    return json(route, 200, { ...record, notes: [], follow_ups: [], revision: 0 });
  });
  await page.goto("/cases");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByText(/Live queue is active/)).toBeVisible();
}

test("case navigation prioritizes the reason for review without presenting exposure as risk", async ({ page }) => {
  await openLiveCases(page);

  const navigator = page.getByRole("navigation", { name: "Case navigator" });
  const highExposureCase = navigator.getByRole("button").filter({ hasText: weakHighExposure.id });
  const lowExposureCase = navigator.getByRole("button").filter({ hasText: strongLowExposure.id });

  await expect(highExposureCase).toContainText(weakHighExposure.merchant);
  await expect(highExposureCase).toContainText("Routine review");
  await expect(highExposureCase).toContainText("New");
  await expect(highExposureCase).toContainText("Unassigned");
  await expect(highExposureCase).not.toContainText("9,500,000");
  await expect(lowExposureCase).toContainText("Velocity spike");
  await expect(lowExposureCase).toContainText("Escalated");
  await expect(lowExposureCase).toContainText("Risk Operations");
  await expect(lowExposureCase).not.toContainText("1.25");

  await lowExposureCase.click();
  await expect(lowExposureCase).toHaveAttribute("aria-current", "true");
  await expect(page).toHaveURL(/case=CASE-LOW-EXPOSURE-STRONG-SIGNAL/);
});

test("selected case explains the signal before showing financial context", async ({ page }, testInfo) => {
  await openLiveCases(page);

  const selected = page.getByRole("region", { name: "Selected alert" });
  await expect(selected).toContainText(weakHighExposure.merchant);
  await expect(selected).toContainText(weakHighExposure.id);
  await expect(selected.getByText("Case ID", { exact: true })).toBeVisible();
  await expect(selected.getByText("Status", { exact: true })).toBeVisible();
  await expect(selected.getByText("Assignment", { exact: true })).toBeVisible();
  await expect(selected.getByRole("heading", { name: "Why this case was flagged" })).toBeVisible();
  await expect(selected.getByRole("heading", { name: "Financial context" })).toBeVisible();
  await expect(selected.getByText("-$9,500,000.25", { exact: true })).toBeVisible();
  await expect(selected).toContainText("Case-linked document status is not available in this view");
  await expect(selected).toContainText("not attached to this case");

  const order = await selected.locator("#signal-heading, #financial-context-heading").evaluateAll((nodes) =>
    nodes.map((node) => node.id)
  );
  expect(order).toEqual(["signal-heading", "financial-context-heading"]);

  const screenshot = testInfo.outputPath("case-decision-hierarchy.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach("case-decision-hierarchy", { path: screenshot, contentType: "image/png" });
});

test("long case content reflows without horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openLiveCases(page);

  const navigator = page.getByRole("navigation", { name: "Case navigator" });
  await expect(navigator.getByText(weakHighExposure.merchant, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

  await navigator.getByRole("button").filter({ hasText: strongLowExposure.id }).click();
  await expect(page.getByRole("heading", { name: "Selected alert" })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("mobile case selection and return preserve the deep link and keyboard focus", async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 });
  await openLiveCases(page);

  const navigator = page.getByRole("navigation", { name: "Case navigator" });
  const target = navigator.getByRole("button").filter({ hasText: strongLowExposure.id });
  await target.click();
  await expect(page).toHaveURL(/case=CASE-LOW-EXPOSURE-STRONG-SIGNAL/);
  await expect(page.getByRole("heading", { name: "Selected alert" })).toBeFocused();
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("Velocity spike");

  await page.getByRole("button", { name: "View case list" }).click();
  await expect(navigator.getByRole("heading", { name: "Cases" })).toBeFocused();
  await expect(target).toHaveAttribute("aria-current", "true");
  await expect(page).toHaveURL(/case=CASE-LOW-EXPOSURE-STRONG-SIGNAL/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("tablet keeps case navigation and detail visible side by side", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await openLiveCases(page);
  const navigator = page.getByRole("navigation", { name: "Case navigator" });
  const selected = page.getByRole("region", { name: "Selected alert" });
  const navBox = await navigator.boundingBox();
  const selectedBox = await selected.boundingBox();
  expect(navBox).not.toBeNull();
  expect(selectedBox).not.toBeNull();
  expect(selectedBox!.x).toBeGreaterThan(navBox!.x + navBox!.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
