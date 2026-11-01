import { expect, test } from "@playwright/test";
import { json } from "../fixtures/api";

test("authentication identifies purpose and associates structured errors without exposing input", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const auth = page.getByRole("region", { name: "Analyst session" });
  await expect(auth.getByLabel("Email", { exact: true })).toHaveAttribute("autocomplete", "username");
  await expect(auth.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "current-password");
  await auth.getByRole("button", { name: "Register", exact: true }).click();
  await expect(auth.getByLabel("Full name")).toHaveAttribute("autocomplete", "name");
  await expect(auth.getByLabel("Email", { exact: true })).toHaveAttribute("autocomplete", "email");
  await expect(auth.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "new-password");
  await page.route("**/api/auth/register", r => json(r, 422, { detail: [
    { loc: ["body", "full_name"], msg: "Full name is required", input: "SECRET_INPUT" },
    { loc: ["body", "password"], msg: "Password exceeds the byte limit", input: "SECRET_PASSWORD" }
  ] }));
  await auth.getByRole("button", { name: "Create account" }).click();
  for (const [label, text] of [["Full name", "Full name is required"], ["Password", "Password exceeds the byte limit"]]) {
    const input = auth.getByLabel(label, { exact: true });
    await expect(input).toHaveAttribute("aria-invalid", "true");
    const errorId = await input.getAttribute("aria-describedby");
    expect(errorId).toBeTruthy();
    await expect(page.locator(`[id="${errorId}"]`)).toContainText(text);
  }
  await expect(auth).not.toContainText("SECRET_");
  await expect(auth.getByLabel("Full name")).toBeFocused();
});

test("workspace ARIA references resolve to actual elements", async ({ page }) => {
  await page.goto("/");
  expect(await page.locator("[aria-labelledby], [aria-describedby]").evaluateAll(nodes => nodes.flatMap(node =>
    ["aria-labelledby", "aria-describedby"].flatMap(attr => (node.getAttribute(attr) || "").split(/\s+/).filter(Boolean).filter(id => !document.getElementById(id)))
  ))).toEqual([]);
});

test("placeholder and essential input borders meet composited contrast thresholds", async ({ page }) => {
  await page.goto("/");
  const values = await page.getByPlaceholder("Search cases, entities, merchants...").evaluate(input => {
    const parse = (value: string) => (value.match(/[\d.]+/g) || []).map(Number);
    const composite = (fg: number[], bg: number[]) => fg.slice(0, 3).map((v, i) => v * (fg[3] ?? 1) + bg[i] * (1 - (fg[3] ?? 1)));
    const luminance = (rgb: number[]) => rgb.map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
    const contrast = (a: number[], b: number[]) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);
    const style = getComputedStyle(input);
    const bg = composite(parse(style.backgroundColor), [255, 255, 255]);
    const placeholder = getComputedStyle(input, "::placeholder");
    const color = parse(placeholder.color);
    color[3] = (color[3] ?? 1) * Number(placeholder.opacity);
    return { placeholder: contrast(composite(color, bg), bg), border: contrast(composite(parse(style.borderTopColor), bg), bg) };
  });
  expect(values.placeholder).toBeGreaterThanOrEqual(4.5);
  expect(values.border).toBeGreaterThanOrEqual(3);
});
