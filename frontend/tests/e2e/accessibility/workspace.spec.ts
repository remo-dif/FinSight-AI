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

test("forms, status regions, and alert queue expose stable accessible names", async ({ page }) => {
  await page.goto("/");

  const sessionTrigger = page.getByRole("button", { name: "Sign in" });
  await sessionTrigger.click();
  await expect(page.getByRole("dialog", { name: "Analyst session" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Analyst session" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(sessionTrigger).toBeFocused();

  await page.getByRole("button", { name: "Ask copilot" }).click();
  await expect(page.getByRole("dialog", { name: "Investigation copilot" })).toBeVisible();
  await expect(page.getByRole("log", { name: "Conversation messages" })).toBeVisible();
  await expect(page.getByRole("form", { name: "Send a message to the finance assistant" })).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  await page.getByRole("button", { name: "Upload evidence" }).click();
  await expect(page.getByRole("dialog", { name: "Evidence ingestion" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Upload processing steps" })).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  if ((page.viewportSize()?.width ?? 1280) < 768) {
    await expect(page.getByRole("list", { name: "Fraud cases" })).toBeVisible();
  } else {
    await expect(
      page.getByRole("table", { name: "Fraud cases with case, assignee, merchant, signal, amount, and status" })
    ).toBeVisible();
  }
});

test("session drawer contains and restores keyboard focus", async ({ page }) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Sign in", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: "Analyst session" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("region", { name: "Analyst session" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close panel" })).toBeVisible();

  await page.keyboard.press("Tab");
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);

  await dialog.getByRole("button", { name: "Close panel" }).click();
  await expect(trigger).toBeFocused();
});

test("keyboard focus has a visible indicator", async ({ page }) => {
  await page.goto("/");
  const skipLink = page.getByRole("link", { name: "Skip to dashboard" });
  await skipLink.focus();
  await page.keyboard.press("Tab");

  const outline = await page.evaluate(() => {
    const element = document.activeElement;
    if (!(element instanceof HTMLElement)) return null;
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor };
  });
  expect(outline).not.toBeNull();
  if (!outline) throw new Error("Keyboard navigation did not focus a workspace control");
  expect(outline.style).toBe("solid");
  expect(Number.parseFloat(outline.width)).toBeGreaterThan(0);
  expect(outline.color).not.toBe("rgba(0, 0, 0, 0)");
});
