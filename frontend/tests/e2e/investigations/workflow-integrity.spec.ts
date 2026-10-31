import { expect, test, type Page } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin } from "../fixtures/api";

async function openLiveCase(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  return page.getByRole("region", { name: "Selected alert" });
}

test("an undecided case can progress without returning to new or resolving directly", async ({ page, isMobile }) => {
  test.skip(isMobile, "case controls are exercised in the full desktop workspace");
  await mockLogin(page);
  await mockDashboardData(page);
  const selected = await openLiveCase(page);
  const status = selected.getByLabel("Status");
  await expect(status).toHaveValue("needs_evidence");
  await expect(status.getByRole("option", { name: "New", exact: true })).toHaveJSProperty("disabled", true);
  await expect(status.getByRole("option", { name: "Resolved", exact: true })).toHaveJSProperty("disabled", true);
  await status.selectOption("escalated");
  await expect(status).toHaveValue("escalated");
  await expect(status.getByRole("option", { name: "New", exact: true })).toHaveJSProperty("disabled", true);
  await status.selectOption("needs_evidence");
  await expect(status).toHaveValue("needs_evidence");
});

for (const decision of ["escalate", "request_verification", "false_positive"] as const) {
  test(`a ${decision} decision locks status while assignment and notes remain available`, async ({ page, isMobile }) => {
    test.skip(isMobile, "case controls are exercised in the full desktop workspace");
    await mockLogin(page);
    await mockDashboardData(page);
    const selected = await openLiveCase(page);
    await selected.getByRole("combobox", { name: /Decision/ }).selectOption(decision);
    await selected.getByLabel("Reason").fill("Evidence supports this investigation outcome.");
    await selected.getByRole("button", { name: "Record decision" }).click();
    await expect(selected).toContainText("Evidence supports this investigation outcome.");
    // Wait for the save/refetch to settle so transient pending-state disabling cannot pass this assertion.
    await expect(selected.getByRole("button", { name: "Assign to me" })).toBeEnabled();
    await expect(selected.getByLabel("Status")).toBeDisabled();
    await expect(selected.getByRole("button", { name: "Record decision" })).toHaveCount(0);
    await selected.getByRole("button", { name: "Assign to me" }).click();
    await expect(selected).toContainText("Assigned to Test Analyst");
    await selected.getByLabel("Add a note").fill("Additional evidence retained after the decision.");
    await selected.getByRole("button", { name: "Add note", exact: true }).click();
    await expect(selected).toContainText("Additional evidence retained after the decision.");
  });
}

test("a legacy resolved case without a decision cannot be reopened or decided through ordinary controls", async ({ page, isMobile }) => {
  test.skip(isMobile, "case controls are exercised in the full desktop workspace");
  await mockLogin(page);
  await mockDashboardData(page);
  const legacyCase = { ...liveTransactions[0], status: "resolved" as const };
  await page.route("**/api/cases?limit=50", async (route) => json(route, 200, [legacyCase]));
  await page.route(`**/api/cases/${legacyCase.id}`, async (route) => json(route, 200, { ...legacyCase, notes: [] }));
  const selected = await openLiveCase(page);
  await expect(selected.getByLabel("Status")).toHaveValue("resolved");
  await expect(selected.getByLabel("Status")).toBeDisabled();
  await expect(selected.getByRole("button", { name: "Record decision" })).toHaveCount(0);
  await expect(selected.getByRole("button", { name: "Assign to me" })).toBeEnabled();
  await expect(selected.getByLabel("Add a note")).toBeEnabled();
});
