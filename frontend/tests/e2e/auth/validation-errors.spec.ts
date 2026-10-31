import { expect, test } from "@playwright/test";
import { json, mockRefreshFailure } from "../fixtures/api";

const passwordMessage = "Value error, Password must be at most 72 UTF-8 bytes; it is never truncated";
const secretInput = "synthetic-sensitive-input-never-render-this";

const validationCases = [
  {
    name: "structured password validation",
    detail: [{ type: "value_error", loc: ["body", "password"], msg: passwordMessage, input: secretInput, ctx: { secret: secretInput } }],
    expected: passwordMessage
  },
  {
    name: "string errors remain compatible",
    detail: "Invalid email or password",
    expected: "Invalid email or password"
  },
  {
    name: "mixed validation messages",
    detail: ["Check the email address", { msg: passwordMessage, input: secretInput }, { msg: 42, input: secretInput }],
    expected: `Check the email address, ${passwordMessage}`
  },
  {
    name: "malformed validation details use a safe fallback",
    detail: [null, {}, { msg: 42, input: secretInput }, false],
    expected: "API request failed: 422"
  }
];

for (const scenario of validationCases) {
  test(`authentication displays ${scenario.name}`, async ({ page, isMobile }) => {
    test.skip(isMobile, "validation rendering is viewport-independent and covered on desktop");
    await mockRefreshFailure(page);
    await page.route("**/api/auth/login", async (route) => json(route, 422, { detail: scenario.detail }));
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    const session = page.getByRole("region", { name: "Analyst session" });
    await session.locator("form button[type='submit']").click();
    await expect(session.getByRole("status")).toHaveText(scenario.expected);
    await expect(session).not.toContainText("[object Object]");
    await expect(session).not.toContainText(secretInput);
    await expect(page.getByText("Live investigation data is active.")).toBeHidden();
  });
}

test("registration displays structured validation messages", async ({ page, isMobile }) => {
  test.skip(isMobile, "validation rendering is viewport-independent and covered on desktop");
  await mockRefreshFailure(page);
  await page.route("**/api/auth/register", async (route) => json(route, 422, {
    detail: [{ type: "value_error", loc: ["body", "password"], msg: passwordMessage, input: secretInput }]
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const session = page.getByRole("region", { name: "Analyst session" });
  await session.getByRole("button", { name: "Register", exact: true }).click();
  await session.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(session.getByRole("status")).toHaveText(passwordMessage);
  await expect(session).not.toContainText(secretInput);
});
