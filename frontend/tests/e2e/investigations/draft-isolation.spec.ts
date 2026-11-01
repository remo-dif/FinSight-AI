import { expect, test, type Page } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin } from "../fixtures/api";

async function openCase(page: Page) {
  await mockLogin(page);
  await mockDashboardData(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type=submit]").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  return page.getByRole("region", { name: "Selected alert" });
}

async function selectCase(page: Page, id: string) {
  const button = page.getByRole("button", { name: id, exact: true });
  await button.focus();
  await page.keyboard.press("Enter");
}

test("decision, reason and note drafts are discarded on keyboard case switching", async ({ page }) => {
  const selected = await openCase(page);
  await selected.getByRole("combobox", { name: /Decision/ }).selectOption("escalate");
  await selected.getByLabel("Reason", { exact: true }).fill("Private draft for A");
  await selected.getByLabel("Add a note").fill("Private note for A");
  await selectCase(page, liveTransactions[1].id);
  await expect(selected.getByRole("combobox", { name: /Decision/ })).toHaveValue("");
  await expect(selected.getByLabel("Reason", { exact: true })).toHaveValue("");
  await expect(selected.getByLabel("Add a note")).toHaveValue("");
  await selectCase(page, liveTransactions[0].id);
  await expect(selected.getByLabel("Reason", { exact: true })).toHaveValue("");
  await expect(selected.getByLabel("Add a note")).toHaveValue("");
});

for (const failure of ["conflict", "network", "timeout"] as const) {
  test(`a late ${failure} for A cannot contaminate B`, async ({ page }) => {
    const selected = await openCase(page);
    let release!: () => void;
    const blocked = new Promise<void>(resolve => { release = resolve; });
    let reads = 0;
    await page.route(`**/api/cases/${liveTransactions[0].id}`, async route => {
      if (route.request().method() === "GET") {
        reads++;
        return json(route, 200, { ...liveTransactions[0], notes: [] });
      }
      expect(route.request().postDataJSON()).toMatchObject({ decision: "escalate", reason: "A only" });
      await blocked;
      if (failure === "network") return route.abort("failed");
      return json(route, 409, { detail: "A changed; refresh before deciding" });
    });
    if (failure === "timeout") await page.clock.install();
    await selected.getByRole("combobox", { name: /Decision/ }).selectOption("escalate");
    await selected.getByLabel("Reason", { exact: true }).fill("A only");
    const request = page.waitForRequest(r => r.method() === "PATCH");
    await selected.getByRole("button", { name: "Record decision" }).click();
    await request;
    const before = reads;
    if (failure === "conflict") {
      release();
      await expect(selected.getByRole("alert")).toContainText("A changed");
      await expect.poll(() => reads).toBeGreaterThan(before);
      await expect(selected.getByLabel("Reason", { exact: true })).toHaveValue("A only");
    }
    await selectCase(page, liveTransactions[1].id);
    await selected.getByLabel("Reason", { exact: true }).fill("B only");
    if (failure === "timeout") await page.clock.fastForward(11000);
    release();
    await expect(selected.getByRole("combobox", { name: /Decision/ })).toHaveValue("");
    await expect(selected.getByLabel("Reason", { exact: true })).toHaveValue("B only");
    await expect(selected.getByRole("alert")).toHaveCount(0);
  });
}
