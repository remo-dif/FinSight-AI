import { expect, test } from "@playwright/test";
import { activateControl, json, mockRefreshFailure } from "../fixtures/api";

test("authentication starts empty with a helpful email example and reflows on mobile", async ({ page, isMobile }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockRefreshFailure(page);
  await page.goto("/");
  await activateControl(page.getByRole("button", { name: "Sign in", exact: true }), isMobile);

  const auth = page.getByRole("region", { name: "Analyst session" });
  const email = auth.getByLabel("Email", { exact: true });
  const password = auth.getByLabel("Password", { exact: true });
  await expect(email).toHaveValue("");
  await expect(email).toHaveAttribute("placeholder", "name@example.com");
  await expect(password).toHaveValue("");

  await activateControl(auth.getByRole("button", { name: "Register", exact: true }), isMobile);
  await expect(auth.getByLabel("Full name", { exact: true })).toHaveValue("");
  await expect(email).toHaveValue("");
  await expect(auth.getByLabel("Password", { exact: true })).toHaveValue("");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("authentication announces pending state and ignores duplicate form submissions", async ({ page }) => {
  let attempts = 0;
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  await mockRefreshFailure(page);
  await page.route("**/api/auth/login", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await blocked;
      await json(route, 401, { detail: "Invalid credentials" });
      return;
    }
    await json(route, 200, { access_token: "test-access-token" });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  const auth = page.getByRole("region", { name: "Analyst session" });
  await auth.getByLabel("Email", { exact: true }).fill("analyst@example.test");
  await auth.getByLabel("Password", { exact: true }).fill("Synthetic-password-42");
  const submit = auth.locator("form button[type='submit']");
  try {
    const request = page.waitForRequest("**/api/auth/login");
    await auth.locator("form").evaluate((form) => {
      if (!(form instanceof HTMLFormElement)) throw new Error("Expected authentication form");
      form.requestSubmit();
      form.requestSubmit();
    });
    await request;

    await expect(submit).toBeDisabled();
    await expect(submit).toHaveAttribute("aria-busy", "true");
    await expect(submit).toHaveAttribute("aria-live", "polite");
    await expect(submit).toHaveAccessibleName("Signing in...");
    await expect(auth.getByRole("status")).toHaveCount(0);
    await expect.poll(() => attempts).toBe(1);
  } finally {
    release();
  }

  await expect(auth.getByRole("alert")).toBeVisible();
  await auth.getByLabel("Password", { exact: true }).fill("Synthetic-password-43");
  const retry = page.waitForRequest("**/api/auth/login");
  await submit.click();
  await retry;
  await expect.poll(() => attempts).toBe(2);
  await expect(auth.getByRole("status")).toContainText("Signed in");
});
