import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockLogin } from "../fixtures/api";

const cases = [
  { amount: "9999999999999999.99", currency: "USD", expected: "$9,999,999,999,999,999.99" },
  { amount: "-0.01", currency: "EUR", expected: "-€0.01" },
  { amount: "0.00", currency: "USD", expected: "$0.00" },
  { amount: "-0.00", currency: "USD", expected: "-$0.00" },
  { amount: "123.456", currency: "USD", expected: "$123.456" },
  { amount: "123", currency: "JPY", expected: "¥123" }
];

test("display preserves decimal strings, signs, precision and currency units", async ({ page }) => {
  await mockLogin(page);
  const records = cases.map((value, index) => ({ ...liveTransactions[0], ...value, id: `DISPLAY-${index}` }));
  await page.route("**/api/cases?limit=50", route => json(route, 200, records));
  await page.route(/\/api\/cases\/DISPLAY-\d+$/, route => {
    const record = records.find(item => route.request().url().endsWith(item.id));
    return json(route, 200, { ...record, notes: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type=submit]").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  const selected = page.getByRole("region", { name: "Selected alert" });
  for (const record of records) {
    const exact = page.getByRole("button", { name: record.id, exact: true });
    const button = await exact.count() ? exact : page.getByRole("list", { name: "Fraud cases" }).getByRole("button").filter({ hasText: record.id });
    await button.click();
    await expect(selected.locator("dd").first()).toHaveText(record.expected);
  }
});

test("the contained desktop table can be scrolled by keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  const queue = page.getByRole("region", { name: "Scrollable alert queue" });
  await queue.focus();
  await expect(queue).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => queue.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
});
