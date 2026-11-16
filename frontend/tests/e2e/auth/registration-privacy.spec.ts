import { expect, test } from "@playwright/test";
import { activateControl, json, mockRefreshFailure } from "../fixtures/api";

for (const scenario of [
  { label: "new account", email: "new.account@example.test" },
  { label: "existing account", email: "existing.account@example.test" }
]) {
  test(`mocked generic HTTP 202 registration gives the same next step for ${scenario.label}`, async ({ page, isMobile }) => {
    let loginRequests = 0;
    let registrationRequests = 0;
    await mockRefreshFailure(page);
    await page.route("**/api/auth/login", (route) => { loginRequests += 1; return json(route, 401, { detail: "Invalid email or password" }); });
    await page.route("**/api/auth/register", (route) => {
      registrationRequests += 1;
      return json(route, 202, { message: "Registration request processed. Sign in with your credentials; existing accounts keep their current password." });
    });
    const refreshResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/refresh"
    );
    await page.goto("/register");
    expect((await refreshResponse).status()).toBe(401);
    const panel = page.getByRole("region", { name: "Analyst session" });
    const fullName = panel.getByLabel("Full name", { exact: true });
    const email = panel.getByLabel("Email", { exact: true });
    const password = panel.getByLabel("Password", { exact: true });
    // Trusted keyboard input avoids WebKit treating synthetic fill operations
    // as a credential-autofill transaction and clearing an adjacent field.
    await fullName.pressSequentially("Synthetic Analyst");
    await email.pressSequentially(scenario.email);
    await password.pressSequentially("Synthetic-registration-password-42");
    await expect(panel.getByLabel("Full name", { exact: true })).toHaveValue("Synthetic Analyst");
    await expect(email).toHaveValue(scenario.email);
    await expect(password).toHaveValue("Synthetic-registration-password-42");
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/register"
    );
    await activateControl(panel.locator("form button[type='submit']"), isMobile);
    const registrationResponse = await responsePromise;
    expect(registrationResponse.status()).toBe(202);
    expect(registrationResponse.request().postDataJSON()).toEqual({
      email: scenario.email,
      password: "Synthetic-registration-password-42",
      full_name: "Synthetic Analyst"
    });
    await expect(page).toHaveURL(/\/login\?returnTo=%2F&registered=1$/);
    await expect(page.getByRole("status").filter({ hasText: "Registration processed" })).toBeVisible();
    await expect(page.getByText("Live investigation data is active.")).toHaveCount(0);
    expect(loginRequests).toBe(0);
    expect(registrationRequests).toBe(1);
  });
}

test("authentication controls work with keyboard and touch", async ({ page }) => {
  await page.goto("/register");
  const panel = page.getByRole("region", { name: "Analyst session" });

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
  await expect(page).toHaveURL(/\/login/);
});
