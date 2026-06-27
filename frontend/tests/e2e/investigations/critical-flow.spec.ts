import { expect, test } from "@playwright/test";
import { mockChatSuccess, mockDashboardData, mockLogin } from "../fixtures/api";

test("analyst can triage a high-risk case through evidence, assistant, and decision panels", async ({ page, isMobile }) => {
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
  await expect(selectedAlert.getByText("High 92", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "CASE-9002" }).click();

  await expect(selectedAlert.getByText("CASE-9002", { exact: true })).toBeVisible();
  await expect(selectedAlert).toContainText(
    "Low-value authorization burst across the same card fingerprint."
  );
  await expect(page.getByRole("button", { name: "Escalate to fraud ops" })).toHaveAttribute("aria-pressed", "true");
  await page.getByText("Audit preview").click();
  await expect(page.getByText("Disposition requires reason code")).toBeVisible();

  await page.getByRole("button", { name: "Ask copilot" }).click();
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("log", { name: "Conversation messages" })).toContainText(
    "CASE-9001 has new-payee risk"
  );
  await expect(page.getByText("Reviewer: Escalate with reason code NEW_PAYEE_HIGH_VALUE.")).toBeVisible();
});
