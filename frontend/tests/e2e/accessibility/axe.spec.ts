import { createRequire } from "node:module";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { activateControl, json, mockDashboardData, mockLogin, mockRefreshFailure } from "../fixtures/api";

const require = createRequire(resolve(process.cwd(), "package.json"));
const axePath = require.resolve("axe-core");
const wcagTags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

type AxeCheck = {
  id: string;
  message: string;
  data?: unknown;
};

type AxeNode = {
  target: string[];
  html: string;
  failureSummary?: string;
  any: AxeCheck[];
  all: AxeCheck[];
  none: AxeCheck[];
};

type AxeRule = {
  id: string;
  impact: string | null;
  help: string;
  nodes: AxeNode[];
};

type AxeResults = {
  violations: AxeRule[];
  incomplete: AxeRule[];
};

type AxeWindow = Window & {
  axe?: {
    run: (
      context: Document,
      options: { runOnly: { type: "tag"; values: string[] } }
    ) => Promise<AxeResults>;
  };
};

async function scan(page: Page, state: string, waitForStable = true, diagnoseContrast = false) {
  if (waitForStable) await page.waitForTimeout(250);
  if (!(await page.evaluate(() => Boolean((window as AxeWindow).axe)))) {
    await page.addScriptTag({ path: axePath });
  }
  const result = await page.evaluate(async (tags) => {
    const axe = (window as AxeWindow).axe;
    if (!axe) throw new Error("axe-core did not initialize in the page");
    return axe.run(document, { runOnly: { type: "tag", values: tags } });
  }, wcagTags);

  const diagnostics = diagnoseContrast && state === "live case settled" && result.incomplete.length
    ? await page.evaluate((nodes) => nodes.map((node) => {
      const selector = node.target[0];
      const element = selector ? document.querySelector(selector) : null;
      if (!element) return { target: node.target, html: node.html, failureSummary: node.failureSummary };

      const layers = [];
      let current: Element | null = element;
      while (current && layers.length < 12) {
        const style = getComputedStyle(current);
        layers.push({
          element: current.id ? `#${current.id}` : current.tagName.toLowerCase(),
          backgroundColor: style.backgroundColor,
          backgroundImage: style.backgroundImage,
          opacity: style.opacity
        });
        current = current.parentElement;
      }

      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const sample = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      let scrollContainer: HTMLElement | null = element.parentElement;
      while (scrollContainer && scrollContainer.scrollWidth <= scrollContainer.clientWidth) {
        scrollContainer = scrollContainer.parentElement;
      }

      const parseColor = (value: string) => {
        const values = value.match(/[\d.]+/g)?.map(Number);
        return values && values.length >= 3
          ? { rgb: values.slice(0, 3), alpha: values[3] ?? 1 }
          : null;
      };
      const effectiveBackground = [255, 255, 255];
      for (const layer of [...layers].reverse()) {
        const color = parseColor(layer.backgroundColor);
        if (color) {
          for (let channel = 0; channel < 3; channel += 1) {
            effectiveBackground[channel] = color.rgb[channel] * color.alpha +
              effectiveBackground[channel] * (1 - color.alpha);
          }
        }
      }
      const luminance = (rgb: number[]) => rgb.map((channel) => channel / 255)
        .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
        .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      const foreground = parseColor(style.color)?.rgb;
      const contrastRatio = foreground
        ? (Math.max(luminance(foreground), luminance(effectiveBackground)) + 0.05) /
          (Math.min(luminance(foreground), luminance(effectiveBackground)) + 0.05)
        : null;
      return {
        target: node.target,
        html: element.outerHTML,
        foreground: style.color,
        effectiveBackground,
        calculatedContrastRatio: contrastRatio,
        viewport: { width: innerWidth, height: innerHeight },
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        opacity: style.opacity,
        centerHit: sample ? {
          element: sample.id ? `#${sample.id}` : sample.tagName.toLowerCase(),
          className: typeof sample.className === "string" ? sample.className : "",
          insideTarget: sample === element || element.contains(sample)
        } : null,
        scrollContainer: scrollContainer ? {
          element: scrollContainer.getAttribute("aria-label") || scrollContainer.tagName.toLowerCase(),
          scrollLeft: scrollContainer.scrollLeft,
          scrollWidth: scrollContainer.scrollWidth,
          clientWidth: scrollContainer.clientWidth,
          overflowX: getComputedStyle(scrollContainer).overflowX
        } : null,
        layers: layers.filter((layer) => ["td", "tr", "section"].includes(layer.element)),
        checks: [...node.any, ...node.all, ...node.none].map((check) => ({
          id: check.id,
          message: check.message,
          data: check.data
        })),
        failureSummary: node.failureSummary
      };
    }), result.incomplete.flatMap((rule) => rule.nodes))
    : [];

  console.log(JSON.stringify({
    state,
    browserType: page.context().browser()?.browserType().name(),
    browserVersion: page.context().browser()?.version(),
    violations: result.violations.map((rule) => ({
      id: rule.id,
      impact: rule.impact,
      help: rule.help,
      targets: rule.nodes.map((node) => node.target)
    })),
    incomplete: result.incomplete.map((rule) => ({
      id: rule.id,
      help: rule.help,
      targets: rule.nodes.map((node) => node.target)
    })),
    incompleteCount: result.incomplete.reduce((count, rule) => count + rule.nodes.length, 0),
    liveCaseContrastDetails: diagnostics
  }, null, 2));
  expect(result.violations, `axe violations in ${state}`).toEqual([]);
  return result;
}

test("axe-core WCAG scans cover the reported workspace states", async ({ page, isMobile, browserName }) => {
  await page.goto("/");
  await scan(page, "anonymous workspace immediate", false);
  await scan(page, "anonymous workspace settled");

  await activateControl(page.getByRole("button", { name: "Sign in", exact: true }), isMobile);
  const auth = page.getByRole("region", { name: "Analyst session" });
  await scan(page, "login");

  await activateControl(auth.getByRole("button", { name: "Register", exact: true }), isMobile);
  await scan(page, "registration");
  await page.route("**/api/auth/register", (route) => json(route, 422, {
    detail: [{ loc: ["body", "password"], msg: "Synthetic validation error", input: "synthetic-password" }]
  }));
  await activateControl(auth.getByRole("button", { name: "Create account", exact: true }), isMobile);
  await expect(auth.getByRole("alert")).toBeVisible();
  await scan(page, "registration field validation");

  await activateControl(auth.getByRole("button", { name: "Sign in", exact: true }), isMobile);
  await mockRefreshFailure(page);
  await mockLogin(page);
  await mockDashboardData(page);
  await activateControl(auth.locator("form button[type='submit']"), isMobile);
  await expect(page.getByText("Live investigation data is active.")).toBeVisible();
  await activateControl(page.getByRole("button", { name: "Close panel" }), isMobile);
  await expect(page.getByRole("region", { name: "Selected alert" })).toContainText("CASE-9001");
  await scan(page, "live case immediate", false);
  await scan(page, "live case settled", true, browserName === "chromium" && !isMobile);
  const queue = page.getByRole("region", { name: "Scrollable alert queue" });
  if (await queue.count()) {
    await queue.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
    const scrolledResult = await scan(page, "live case table scrolled to end");
    const incompleteTargets = scrolledResult.incomplete.flatMap((rule) =>
      rule.nodes.flatMap((node) => node.target)
    );
    expect(incompleteTargets).not.toContain(".cursor-pointer:nth-child(1) > .text-right");
    expect(incompleteTargets).not.toContain(".cursor-pointer:nth-child(1) > .break-words");
    expect(incompleteTargets).not.toContain(".cursor-pointer:nth-child(2) > .text-right");
    expect(incompleteTargets).not.toContain(".cursor-pointer:nth-child(2) > .break-words");
  }

  await activateControl(page.getByRole("button", { name: "Ask copilot" }), isMobile);
  await scan(page, "copilot");
  await activateControl(page.getByRole("button", { name: "Close panel" }), isMobile);
  await activateControl(page.getByRole("button", { name: "Upload evidence" }), isMobile);
  await scan(page, "upload");
});
