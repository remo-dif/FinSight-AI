import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockRefreshFailure } from "../fixtures/api";

async function expectInsideNavigation(navigation: Locator, activeLink: Locator) {
  await expect(activeLink).toHaveAttribute("aria-current", "page");
  await expect.poll(async () => {
    const navigationBox = await navigation.boundingBox();
    const linkBox = await activeLink.boundingBox();
    if (!navigationBox || !linkBox) return false;
    return linkBox.x >= navigationBox.x - 1
      && linkBox.x + linkBox.width <= navigationBox.x + navigationBox.width + 1;
  }).toBe(true);
}

async function activeLink(page: Page, label: string) {
  return page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: new RegExp(`^${label}`) });
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockRefreshFailure(page);
});

test("mobile navigation prioritizes available workspaces and keeps route history visible", async ({ page }) => {
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
  await expect(navigation.getByRole("link")).toHaveCount(6);
  await expect(navigation.getByRole("link")).toHaveText([
    "Triage",
    "Cases",
    "Evidence",
    "GraphComing soon",
    "DataComing soon",
    "ControlsComing soon"
  ]);

  for (const destination of [
    { path: "/", label: "Triage" },
    { path: "/cases", label: "Cases" },
    { path: "/evidence", label: "Evidence" },
    { path: "/graph", label: "Graph" },
    { path: "/data", label: "Data" },
    { path: "/controls", label: "Controls" }
  ]) {
    await page.goto(destination.path);
    await expectInsideNavigation(navigation, await activeLink(page, destination.label));
  }

  await page.goto("/");
  await (await activeLink(page, "Evidence")).click();
  await expect(page).toHaveURL(/\/evidence$/);
  await expectInsideNavigation(navigation, await activeLink(page, "Evidence"));

  await (await activeLink(page, "Graph")).click();
  await expect(page).toHaveURL(/\/graph$/);
  await expectInsideNavigation(navigation, await activeLink(page, "Graph"));

  await page.goBack();
  await expect(page).toHaveURL(/\/evidence$/);
  await expectInsideNavigation(navigation, await activeLink(page, "Evidence"));

  await page.goForward();
  await expect(page).toHaveURL(/\/graph$/);
  await expectInsideNavigation(navigation, await activeLink(page, "Graph"));

  await page.goto("/controls");
  await expectInsideNavigation(navigation, await activeLink(page, "Controls"));
});

for (const width of [320, 390, 768]) {
  test(`direct navigation keeps the active destination visible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/controls");
    const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
    await expectInsideNavigation(navigation, await activeLink(page, "Controls"));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
}

test("mobile navigation communicates horizontal overflow without moving the page", async ({ page }) => {
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
  const endIndicator = page.locator('[data-scroll-indicator="end"]');
  const startIndicator = page.locator('[data-scroll-indicator="start"]');
  await expect(endIndicator).toBeVisible();
  await expect(startIndicator).toHaveCount(0);

  const initialWindowScroll = await page.evaluate(() => window.scrollY);
  await navigation.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect(startIndicator).toBeVisible();
  await expect(endIndicator).toHaveCount(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(initialWindowScroll);

  const badges = navigation.getByText("Coming soon", { exact: true });
  await expect(badges).toHaveCount(3);
  for (const badge of await badges.all()) {
    expect(await badge.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(12);
  }

  const linkHeights = await navigation.getByRole("link").evaluateAll((links) =>
    links.map((link) => link.getBoundingClientRect().height)
  );
  expect(linkHeights.every((height) => height >= 44)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
