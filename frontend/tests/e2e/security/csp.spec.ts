import { expect, test } from "@playwright/test";

test("script CSP uses fresh nonces and blocks unauthorized inline execution", async ({ page, request }) => {
  const response = await page.goto("/");
  const policy = response?.headers()["content-security-policy"] ?? "";
  const scriptPolicy = policy.split(";").find((part) => part.trim().startsWith("script-src ")) ?? "";
  expect(scriptPolicy).not.toContain("'unsafe-inline'");
  const nonce = scriptPolicy.match(/'nonce-([^']+)'/)?.[1];
  expect(nonce).toBeTruthy();
  const inlineNonces = await page.locator("script:not([src])").evaluateAll((scripts) => scripts.map((script) => (script as HTMLScriptElement).nonce));
  expect(inlineNonces.length).toBeGreaterThan(0);
  expect(inlineNonces.every((value) => value === nonce)).toBe(true);
  await page.evaluate(() => {
    const script = document.createElement("script");
    script.textContent = "window.__untrustedInlineExecuted = true";
    document.body.appendChild(script);
  });
  expect(await page.evaluate(() => (window as Window & { __untrustedInlineExecuted?: boolean }).__untrustedInlineExecuted)).toBeUndefined();
  const second = await request.get("/", { headers: { "x-nonce": "attacker-nonce", "content-security-policy": "script-src 'unsafe-inline'" } });
  const secondPolicy = second.headers()["content-security-policy"] ?? "";
  expect(secondPolicy).not.toContain(`'nonce-${nonce}'`);
  expect(secondPolicy).not.toContain("attacker-nonce");
  expect(secondPolicy).toContain("'nonce-");
  await page.getByRole("button", { name: "Upload evidence" }).click();
  await expect(page.locator("input[type=file]")).toBeAttached();
});
