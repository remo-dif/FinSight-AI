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
  const exact = page.getByRole("button", { name: id, exact: true });
  const button = await exact.count() ? exact : page.getByRole("list", { name: "Fraud cases" }).getByRole("button").filter({ hasText: id });
  await button.focus();
  await page.keyboard.press("Enter");
}

test("decision, reason and note drafts are discarded on keyboard case switching", async ({ page }) => {
  const selected = await openCase(page);
  await selected.getByRole("combobox", { name: /Decision/ }).selectOption("escalate");
  await selected.getByRole("textbox", { name: /^Reason/ }).fill("Private draft for A");
  await selected.getByLabel("Add a note").fill("Private note for A");
  await selectCase(page, liveTransactions[1].id);
  await expect(selected.getByRole("combobox", { name: /Decision/ })).toHaveValue("");
  await expect(selected.getByRole("textbox", { name: /^Reason/ })).toHaveValue("");
  await expect(selected.getByLabel("Add a note")).toHaveValue("");
  await selectCase(page, liveTransactions[0].id);
  await expect(selected.getByRole("textbox", { name: /^Reason/ })).toHaveValue("");
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
    await selected.getByRole("textbox", { name: /^Reason/ }).fill("A only");
    const request = page.waitForRequest(r => r.method() === "PATCH");
    await selected.getByRole("button", { name: "Record decision" }).click();
    await request;
    const before = reads;
    if (failure === "conflict") {
      release();
      await expect(selected.getByRole("alert")).toContainText("A changed");
      await expect.poll(() => reads).toBeGreaterThan(before);
      await expect(selected.getByRole("textbox", { name: /^Reason/ })).toHaveValue("A only");
    }
    await selectCase(page, liveTransactions[1].id);
    await selected.getByRole("textbox", { name: /^Reason/ }).fill("B only");
    if (failure === "timeout") await page.clock.fastForward(11000);
    release();
    await expect(selected.getByRole("combobox", { name: /Decision/ })).toHaveValue("");
    await expect(selected.getByRole("textbox", { name: /^Reason/ })).toHaveValue("B only");
    await expect(selected.getByRole("alert")).toHaveCount(0);
  });
}

for (const kind of ["decision", "note"] as const) {
  test(`a delayed successful ${kind} stays on A and preserves B's new draft`, async ({ page }) => {
    const selected = await openCase(page);
    let release!: () => void;
    const blocked = new Promise<void>(resolve => { release = resolve; });
    const suffix = kind === "note" ? "/notes" : "";
    await page.route(`**/api/cases/${liveTransactions[0].id}${suffix}`, async route => {
      if (route.request().method() === "GET") return route.fallback();
      expect(new URL(route.request().url()).pathname).toBe(`/api/cases/${liveTransactions[0].id}${suffix}`);
      expect(route.request().postDataJSON()).toMatchObject(kind === "note" ? { content: "A saved note" } : { decision: "escalate", reason: "A saved decision" });
      await blocked;
      return route.fallback();
    });
    try {
      if (kind === "note") await selected.getByLabel("Add a note").fill("A saved note");
      else {
        await selected.getByRole("combobox", { name: /Decision/ }).selectOption("escalate");
        await selected.getByRole("textbox", { name: /^Reason/ }).fill("A saved decision");
      }
      const request = page.waitForRequest(r => r.method() === (kind === "note" ? "POST" : "PATCH"));
      await selected.getByRole("button", { name: kind === "note" ? "Add note" : "Record decision", exact: true }).click();
      await request;
      await selectCase(page, liveTransactions[1].id);
      await selected.getByLabel("Add a note").fill("B draft must survive");
      const response = page.waitForResponse(r => r.request().method() === (kind === "note" ? "POST" : "PATCH"));
      release();
      await response;
      await expect(selected.getByLabel("Add a note")).toHaveValue("B draft must survive");
      await expect(selected).not.toContainText("A saved");
      await selectCase(page, liveTransactions[0].id);
      await expect(selected).toContainText(kind === "note" ? "A saved note" : "A saved decision");
    } finally { release(); }
  });
}

test("follow-up drafts and captured revisions stay with their intended case", async ({ page }) => {
  await mockLogin(page);
  await mockDashboardData(page);
  const records = liveTransactions.map((r, i) => ({ ...r, decision: "escalate", status: "escalated", decision_reason: "Initial", revision: 7 + i }));
  await page.route("**/api/cases?limit=50", r => json(r, 200, records));
  await page.route("**/api/cases/*", r => {
    const record = records.find(item => item.id === new URL(r.request().url()).pathname.split("/")[3]);
    return json(r, 200, { ...record, notes: [], follow_ups: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type=submit]").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  const selected = page.getByRole("region", { name: "Selected alert" });
  await selected.getByLabel("Escalation investigation outcome").fill("A draft");
  await selectCase(page, records[1].id);
  await expect(selected.getByLabel("Escalation investigation outcome")).toHaveValue("");
  await selectCase(page, records[0].id);
  await expect(selected.getByLabel("Escalation investigation outcome")).toHaveValue("");
  let sent = 0;
  await page.route(`**/api/cases/${records[0].id}/follow-ups`, r => {
    sent++;
    expect(r.request().postDataJSON()).toMatchObject({ expected_revision: 7, reason: "A outcome" });
    records[0].revision = 9;
    return json(r, 409, { detail: "Concurrent change; review refreshed case" });
  });
  await selected.getByLabel("Escalation investigation outcome").fill("A outcome");
  await selected.getByRole("button", { name: "Record follow-up outcome" }).click();
  await expect(selected.getByRole("alert")).toContainText("Concurrent change");
  await expect(selected.getByLabel("Escalation investigation outcome")).toHaveValue("A outcome");
  expect(sent).toBe(1);
});
