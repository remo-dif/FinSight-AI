import { expect, test } from "@playwright/test";
import { activateControl, json } from "../fixtures/api";

for (const scenario of ["new account", "existing account"]) {
  test(`mocked generic HTTP 202 registration gives the same next step for ${scenario}`, async ({ page, isMobile }) => {
    let loginRequests = 0;
    let registrationRequests = 0;
    await page.route("**/api/auth/login", (route) => { loginRequests += 1; return json(route, 401, { detail: "Invalid email or password" }); });
    await page.route("**/api/auth/register", (route) => {
      registrationRequests += 1;
      return json(route, 202, { message: "Registration request processed. Sign in with your credentials; existing accounts keep their current password." });
    });
    await page.goto("/");
    await activateControl(page.getByRole("button", { name: "Sign in" }), isMobile);
    const panel = page.getByRole("region", { name: "Analyst session" });
    await activateControl(panel.getByRole("button", { name: "Register", exact: true }), isMobile);
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/register"
    );
    await activateControl(panel.locator("form button[type='submit']"), isMobile);
    expect((await responsePromise).status()).toBe(202);
    await expect(panel).toContainText("Registration request processed.");
    await expect(panel).not.toContainText("Account created");
    await expect(panel.getByRole("button", { name: "Sign in", exact: true, pressed: true })).toHaveAttribute("aria-pressed", "true");
    expect(loginRequests).toBe(0);
    expect(registrationRequests).toBe(1);
  });
}

test("authentication controls work with keyboard and touch", async ({ page, isMobile }) => {
  await page.goto("/");
  const signIn = page.getByRole("button", { name: "Sign in", exact: true });
  await signIn.focus();
  await page.keyboard.press("Enter");

  const panel = page.getByRole("region", { name: "Analyst session" });
  const register = panel.getByRole("button", { name: "Register", exact: true });
  await activateControl(register, isMobile);
  await expect(register).toHaveAttribute("aria-pressed", "true");

  const fullName = panel.getByLabel("Full name", { exact: true });
  const email = panel.getByLabel("Email", { exact: true });
  const password = panel.getByLabel("Password", { exact: true });
  for (const [field, value] of [
    [fullName, "Synthetic Analyst"],
    [email, "synthetic.analyst@example.test"],
    [password, "Synthetic-password-42"]
  ] as const) {
    await field.focus();
    await page.keyboard.press("Control+A");
    await page.keyboard.type(value);
  }

  await page.route("**/api/auth/register", (route) =>
    json(route, 202, { message: "Registration request processed. Sign in with your credentials." })
  );
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/register"
  );
  const submit = panel.getByRole("button", { name: "Create account", exact: true });
  await submit.focus();
  await page.keyboard.press("Enter");
  expect((await responsePromise).status()).toBe(202);
  await expect(panel).toContainText("Registration request processed.");
});
