import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin } from "../fixtures/api";

for (const width of [1440, 768, 375, 320]) {
  test(`full identifiers and exact large amounts remain available with text spacing at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockLogin(page);
    await mockDashboardData(page);
    const record = { ...liveTransactions[0], id: "12345678-abcd-4321-abcd-123456789abc", amount: "-9999999999999999.99" };
    await page.route("**/api/cases?limit=50", r => json(r, 200, [record]));
    await page.route(`**/api/cases/${record.id}`, r => json(r, 200, { ...record, notes: [] }));
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("region", { name: "Analyst session" }).locator("form button[type=submit]").click();
    await expect(page.getByText("Live investigation data is active.")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await page.addStyleTag({ content: "* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }" });
    const selected = page.getByRole("region", { name: "Selected alert" });
    await expect(selected).toContainText(record.id);
    await expect(selected).toContainText("-" + "$9,999,999,999,999,999.99");
    expect(await selected.locator("dd").evaluateAll(nodes => nodes.every(n => n.scrollWidth <= n.clientWidth + 1))).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
