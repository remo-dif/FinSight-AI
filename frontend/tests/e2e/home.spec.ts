import { expect, test } from "@playwright/test";

test("renders finance workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Personal Finance AI Assistant" })).toBeVisible();
  await expect(page.getByText("Net Cash Flow")).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI Financial Assistant" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Secure Upload" })).toBeVisible();
});

test("keeps upload controls constrained to supported financial files", async ({ page }) => {
  await page.goto("/");

  const fileInput = page.locator("input[type='file']");
  await expect(fileInput).toHaveAttribute("accept", ".csv,.pdf,.png,.jpg,.jpeg");
  await expect(page.getByRole("button", { name: "Upload" })).toBeDisabled();
  await expect(page.getByText("Files are validated before processing.")).toBeVisible();
});
