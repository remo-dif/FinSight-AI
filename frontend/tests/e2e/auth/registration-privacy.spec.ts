import { expect, test } from "@playwright/test";
import { json } from "../fixtures/api";

for (const scenario of ["new account", "existing account"]) {
  test(`registration gives the same next step for ${scenario}`, async ({ page, isMobile }) => {
    test.skip(isMobile, "Registration form is exercised in the desktop session panel.");
    let loginRequests = 0;
    await page.route("**/api/auth/login", (route) => { loginRequests += 1; return json(route, 401, { detail: "Invalid email or password" }); });
    await page.route("**/api/auth/register", (route) => json(route, 202, { message: "Registration request processed. Sign in with your credentials; existing accounts keep their current password." }));
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in" }).click();
    const panel = page.getByRole("region", { name: "Analyst session" });
    await panel.getByRole("button", { name: "Register", exact: true }).click();
    await panel.locator("form button[type='submit']").click();
    await expect(panel).toContainText("Registration request processed.");
    await expect(panel).not.toContainText("Account created");
    await expect(panel.getByRole("button", { name: "Sign in", exact: true, pressed: true })).toHaveAttribute("aria-pressed", "true");
    expect(loginRequests).toBe(0);
  });
}
