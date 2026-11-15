import { expect, test, type Page } from "@playwright/test";
import { analystTokens, json } from "../fixtures/api";

async function anonymousSession(page: Page) {
  await page.route("**/api/auth/refresh", route => json(route, 401, { detail: "No refresh session" }));
}

test("offers a dedicated login without exposing registration or blocking demo access", async ({ page }) => {
  await anonymousSession(page);
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "Sign in to FinSight AI" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Analyst session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Register" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Continue with demo data" })).toHaveAttribute("href", "/");
});

test("returns to a validated internal destination after login", async ({ page }) => {
  await anonymousSession(page);
  await page.route("**/api/auth/login", route => json(route, 200, analystTokens));
  await page.goto("/login?returnTo=%2Fcases%3Fcase%3DCASE-1042");

  const session = page.getByRole("region", { name: "Analyst session" });
  await session.getByLabel("Email").fill("analyst@example.com");
  await session.getByLabel("Password").fill("correct horse battery staple");
  await session.locator("form button[type=submit]").click();

  await expect(page).toHaveURL(/\/cases\?case=CASE-1042$/);
});

test("the shell sign-in destination preserves the current case query", async ({ page }) => {
  await anonymousSession(page);
  await page.goto("/cases?case=CASE-1042");
  const signIn = page.getByRole("link", { name: "Sign in", exact: true });
  await expect(signIn).toHaveAttribute("href", "/login?returnTo=%2Fcases%3Fcase%3DCASE-1042");
  await signIn.click();
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fcases%3Fcase%3DCASE-1042$/);
});

for (const unsafe of ["https://example.com/steal", "//example.com/steal", "/login?returnTo=/cases", "/it/login"]) {
  test(`rejects unsafe or looping returnTo ${unsafe}`, async ({ page }) => {
    await anonymousSession(page);
    await page.route("**/api/auth/login", route => json(route, 200, analystTokens));
    await page.goto(`/login?returnTo=${encodeURIComponent(unsafe)}`);
    const session = page.getByRole("region", { name: "Analyst session" });
    await session.getByLabel("Email").fill("analyst@example.com");
    await session.getByLabel("Password").fill("correct horse battery staple");
    await session.locator("form button[type=submit]").click();
    await expect(page).toHaveURL("/");
  });
}

test("an existing server session redirects only after restoration is confirmed", async ({ page }) => {
  await page.route("**/api/auth/refresh", route => json(route, 200, analystTokens));
  await page.goto("/login?returnTo=%2Fevidence");
  await expect(page).toHaveURL(/\/evidence$/);
});

test("supports the localized login route", async ({ page }) => {
  await anonymousSession(page);
  await page.goto("/it/login");
  await expect(page.getByRole("heading", { name: "Accedi a FinSight AI" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Registrati" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Continua con i dati dimostrativi" })).toHaveAttribute("href", "/it");
});
