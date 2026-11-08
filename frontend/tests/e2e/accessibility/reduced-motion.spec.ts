import { expect, test } from "@playwright/test";
import { json, mockLogin, mockRefreshFailure } from "../fixtures/api";

test("reduced motion preserves focus, dialogs, navigation, and page geometry", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockRefreshFailure(page);
  await page.goto("/cases");

  const sessionTrigger = page.getByRole("button", { name: "Sign in", exact: true });
  await sessionTrigger.focus();
  const focusStyle = await sessionTrigger.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(focusStyle.outlineStyle).toBe("solid");
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThan(0);

  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Analyst session" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close panel" }).click();
  await expect(sessionTrigger).toBeFocused();

  const geometry = await page.evaluate(() => ({
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
    maxScrollY: document.documentElement.scrollHeight - window.innerHeight
  }));
  expect(geometry.horizontalOverflow).toBe(false);

  if ((page.viewportSize()?.width ?? 1280) < 768) {
    const mobileNavigation = page.getByRole("navigation", { name: "Mobile navigation" });
    await expect(mobileNavigation).toBeVisible();
    expect(geometry.maxScrollY).toBeGreaterThan(0);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    const headerTop = await page.locator("header").evaluate((header) => header.getBoundingClientRect().top);
    expect(Math.abs(headerTop)).toBeLessThanOrEqual(1);
    await expect(mobileNavigation.getByRole("link", { name: "Cases", exact: true })).toBeVisible();
  }
});

test("loading animations are disabled when reduced motion is requested", async ({ page }) => {
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockLogin(page);
  await mockRefreshFailure(page);
  await page.route("**/api/uploads", async (route) => {
    await blocked;
    await json(route, 200, { status: "accepted", imported: 1, indexed: 1 });
  });
  await page.goto("/cases");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const auth = page.getByRole("region", { name: "Analyst session" });
  await auth.getByLabel("Email", { exact: true }).fill("analyst@example.test");
  await auth.getByLabel("Password", { exact: true }).fill("Synthetic-password-42");
  await auth.locator("form button[type='submit']").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("dialog", { name: "Analyst session" }).getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Upload evidence" }).click();

  const upload = page.getByRole("dialog", { name: "Evidence ingestion" });
  await upload.locator('input[type="file"]').setInputFiles({
    name: "synthetic.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("date,amount\n2026-01-01,1\n")
  });
  try {
    const request = page.waitForRequest("**/api/uploads");
    await upload.getByRole("button", { name: "Upload", exact: true }).click();
    await request;
    const spinner = upload.locator("svg.animate-spin").first();
    await expect(spinner).toBeVisible();
    await expect.poll(() => spinner.evaluate((element) => getComputedStyle(element).animationName)).toBe("none");
  } finally {
    release();
  }
});
