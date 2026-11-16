import { expect, test } from "@playwright/test";
import { json, mockRefreshFailure } from "../fixtures/api";

test("registration is available only on the dedicated route", async ({ context, page }) => {
  for (const path of ["/", "/cases"]) {
    const workspace = await context.newPage();
    await mockRefreshFailure(workspace);
    try {
      await workspace.goto(path);
      await workspace.getByRole("link", { name: "Sign in", exact: true }).click();
      const session = workspace.getByRole("region", { name: "Analyst session" });
      await expect(session.getByRole("button", { name: "Register", exact: true })).toHaveCount(0);
      await expect(session.getByRole("button", { name: "Create account", exact: true })).toHaveCount(0);
    } finally {
      await workspace.close();
    }
  }

  await mockRefreshFailure(page);
  await page.goto("/evidence");
  const evidenceSession = page.getByRole("region", { name: "Analyst session" });
  await expect(evidenceSession.getByRole("button", { name: "Register", exact: true })).toHaveCount(0);
  await expect(evidenceSession.getByRole("button", { name: "Create account", exact: true })).toHaveCount(0);

  await page.goto("/login");
  await page.getByRole("link", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/register/);
  await expect(page.getByRole("heading", { name: "Create your FinSight AI account" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create account", exact: true })).toBeVisible();
});

test("registration preserves the requested destination for the following login", async ({ page }) => {
  await mockRefreshFailure(page);
  await page.route("**/api/auth/register", route => json(route, 202, { message: "Registration request processed." }));
  await page.goto("/register?returnTo=%2Fcases%3Fcase%3DCASE-1042");
  const form = page.getByRole("region", { name: "Analyst session" });
  await form.getByLabel("Full name").fill("Synthetic Analyst");
  await form.getByLabel("Email").fill("analyst@example.test");
  await form.getByLabel("Password").fill("Synthetic-password-42");
  await form.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fcases%3Fcase%3DCASE-1042&registered=1$/);
});

test("supports the localized registration route", async ({ page }) => {
  await mockRefreshFailure(page);
  await page.goto("/it/register");
  await expect(page.getByRole("heading", { name: "Crea il tuo account FinSight AI" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Crea account" })).toBeVisible();
});
