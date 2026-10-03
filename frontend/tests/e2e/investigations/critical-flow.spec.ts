import { expect, test } from "@playwright/test";
import { mockChatSuccess, mockDashboardData, mockLogin } from "../fixtures/api";

test("analyst can update case state, record a decision and note, then use the copilot", async ({ page, isMobile }) => {
  test.skip(isMobile, "critical workflow is covered on desktop where the full analyst workspace is visible");

  await mockLogin(page);
  await mockDashboardData(page);
  await mockChatSuccess(page);

  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page
    .getByRole("region", { name: "Analyst session" })
    .locator("form button[type='submit']")
    .click();

  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  const selectedAlert = page.getByRole("region", { name: "Selected alert" });
  await expect(selectedAlert.getByText("CASE-9001", { exact: true })).toBeVisible();
  await expect(selectedAlert).toContainText("Wire mule cluster");

  await page.getByRole("button", { name: "CASE-9002" }).click();

  await expect(selectedAlert.getByText("CASE-9002", { exact: true })).toBeVisible();
  await expect(selectedAlert).toContainText(
    "Low-value authorization burst across the same card fingerprint."
  );
  const status = selectedAlert.getByLabel("Status");
  await expect(status).toHaveValue("new");
  await status.selectOption("escalated");
  await expect(status).toHaveValue("escalated");

  await selectedAlert.getByRole("button", { name: "Assign to me" }).click();
  await expect(selectedAlert).toContainText("Assigned to Test Analyst");

  await selectedAlert.getByRole("combobox", { name: /Decision/ }).selectOption("request_verification");
  await selectedAlert.getByLabel("Reason").fill("Customer activity needs confirmation.");
  await selectedAlert.getByRole("button", { name: "Record decision" }).click();
  await expect(selectedAlert).toContainText("Request customer verification");
  await expect(selectedAlert).toContainText("Customer activity needs confirmation.");

  await selectedAlert.getByLabel("Add a note").fill("Reviewed the transaction origin with the customer.");
  await selectedAlert.getByRole("button", { name: "Add note" }).click();
  await expect(selectedAlert).toContainText("Reviewed the transaction origin with the customer.");

  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("log", { name: "Conversation messages" })).toContainText(
    "CASE-9001 has new-payee risk"
  );
  await expect(page.getByText("Reviewer: Escalate with reason code NEW_PAYEE_HIGH_VALUE.")).toBeVisible();
});
