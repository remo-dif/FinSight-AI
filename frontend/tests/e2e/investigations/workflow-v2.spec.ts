import { expect, test } from "@playwright/test";
import { json, liveTransactions, mockDashboardData, mockLogin } from "../fixtures/api";
import type { CaseFollowUp } from "@/lib/api";

for (const decision of ["escalate", "request_verification"] as const) {
  test(`${decision} records an outcome and closes without replacing the decision`, async ({ page, isMobile }) => {
    test.skip(isMobile, "The investigation controls are in the desktop workspace.");
    await mockLogin(page);
    await mockDashboardData(page);
    const record = { ...liveTransactions[0], decision, decision_reason: "Immutable initial decision", status: decision === "escalate" ? "escalated" : "needs_evidence", revision: 1 };
    const history: CaseFollowUp[] = [];
    await page.route("**/api/cases?limit=50", (route) => json(route, 200, [record]));
    await page.route(`**/api/cases/${record.id}`, (route) => json(route, 200, { ...record, notes: [], follow_ups: history }));
    await page.route(`**/api/cases/${record.id}/follow-ups`, async (route) => {
      const payload = route.request().postDataJSON();
      expect(payload.expected_revision).toBe(1);
      expect(payload.action).toBe(decision === "escalate" ? "escalation_outcome" : "verification_outcome");
      record.revision = 2;
      const outcome = { id: "follow-up-1", case_id: record.id, actor_id: "actor-1", action: payload.action, reason: payload.reason, previous_status: record.status, resulting_status: record.status, revision: 2, created_at: "2026-10-31T12:00:00Z" } as CaseFollowUp;
      history.push(outcome);
      await json(route, 201, outcome);
    });
    await page.route(`**/api/cases/${record.id}/close`, async (route) => {
      const payload = route.request().postDataJSON();
      expect(payload.expected_revision).toBe(2);
      history.push({ ...history[0], id: "follow-up-2", action: "close", reason: payload.reason, resulting_status: "resolved", revision: 3 });
      record.status = "resolved";
      record.revision = 3;
      await json(route, 200, record);
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
    await expect(page.getByText("Live investigation data is active.")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    const selected = page.getByRole("region", { name: "Selected alert" });
    const outcomeLabel = decision === "escalate" ? "Escalation investigation outcome" : "Verification result and outcome";
    await expect(selected.getByRole("button", { name: "Record follow-up outcome" })).toBeDisabled();
    await selected.getByLabel(outcomeLabel).fill("Additional evidence reviewed");
    await selected.getByRole("button", { name: "Record follow-up outcome" }).click();
    await expect(selected).toContainText("Additional evidence reviewed");
    await selected.getByLabel("Closure reason").fill("Operational investigation complete");
    await selected.getByRole("button", { name: "Close investigation" }).click();
    await expect(selected).toContainText("This case is closed.");
    await expect(selected).toContainText("Notes are read-only after closure.");
    await expect(selected).not.toContainText("Sign in to add notes");
    await expect(selected).toContainText("Immutable initial decision");
    await expect(selected.getByRole("button", { name: "Assign to me" })).toBeDisabled();
    await expect(selected.getByLabel("Add a note")).toHaveCount(0);
    await expect(selected.getByRole("button", { name: "Close investigation" })).toHaveCount(0);
    const items = selected.getByRole("heading", { name: "Follow-up investigation" }).locator("..").getByRole("listitem");
    await expect(items).toHaveCount(2);
    await expect(items.nth(0)).toContainText("Additional evidence reviewed");
    await expect(items.nth(1)).toContainText("Operational investigation complete");
  });
}

test("follow-up conflicts remain visible and refresh the case", async ({ page, isMobile }) => {
  test.skip(isMobile, "The investigation controls are in the desktop workspace.");
  await mockLogin(page);
  await mockDashboardData(page);
  const record = { ...liveTransactions[0], decision: "escalate", status: "escalated", decision_reason: "Original", revision: 1 };
  let reads = 0;
  await page.route("**/api/cases?limit=50", (route) => json(route, 200, [record]));
  await page.route(`**/api/cases/${record.id}`, (route) => { reads += 1; return json(route, 200, { ...record, notes: [], follow_ups: [] }); });
  await page.route(`**/api/cases/${record.id}/follow-ups`, (route) => json(route, 409, { detail: "Case changed while saving. Refresh the case and retry" }));
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("region", { name: "Analyst session" }).locator("form button[type='submit']").click();
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  const selected = page.getByRole("region", { name: "Selected alert" });
  await selected.getByLabel("Escalation investigation outcome").fill("Reviewed");
  const before = reads;
  await selected.getByRole("button", { name: "Record follow-up outcome" }).click();
  await expect(selected.getByRole("alert")).toContainText("Case changed while saving");
  await expect.poll(() => reads).toBeGreaterThan(before);
  await expect(selected.getByLabel("Escalation investigation outcome")).toHaveValue("Reviewed");
});
