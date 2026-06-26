import { expect, test } from "@playwright/test";

test("primary workspace controls are reachable by keyboard", async ({ page, isMobile }) => {
  test.skip(isMobile, "keyboard traversal is covered on desktop");

  await page.goto("/");

  const skipLink = page.getByRole("link", { name: "Skip to dashboard" });
  await skipLink.focus();
  await expect(skipLink).toBeFocused();

  const triageLink = page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Triage" });
  await triageLink.focus();
  await expect(triageLink).toBeFocused();

  const casesLink = page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Cases" });
  await casesLink.focus();
  await expect(casesLink).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/cases$/);
  await expect(page.getByRole("heading", { name: "Review assigned cases and escalation state" })).toBeVisible();
});

test("forms, status regions, and data table expose stable accessible names", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("region", { name: "Analyst session" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  await page.getByRole("button", { name: "Ask copilot" }).click();
  await expect(page.getByRole("log", { name: "Conversation messages" })).toBeVisible();
  await expect(page.getByRole("form", { name: "Send a message to the finance assistant" })).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  await page.getByRole("button", { name: "Upload evidence" }).click();
  await expect(page.getByRole("list", { name: "Upload processing steps" })).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  await expect(page.getByRole("table", { name: "Open fraud alerts with case, risk, entity, signal, amount, SLA, status, and owner" })).toBeVisible();
});
