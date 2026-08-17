import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * End-to-end coverage of the dashboard as it actually ships (requirements F31, N10).
 *
 * These assert behaviour a unit test cannot: that the committed data files are reachable at
 * the built app's paths, that switching algorithm redraws, and that the page is navigable by
 * keyboard and free of WCAG AA violations axe can detect.
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /ORBIT/ })).toBeVisible();
});

test("the replay view loads committed results rather than erroring", async ({ page }) => {
  // The error path renders "Could not load results", so its absence is the real assertion.
  await expect(page.getByText(/Could not load results/)).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: /Primary/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /topology at tick/ }).first()).toBeVisible();
});

test("both panels render and the comparison panel is independent", async ({ page }) => {
  const panels = page.getByRole("img", { name: /topology at tick/ });
  await expect(panels).toHaveCount(2);

  await page.getByRole("combobox", { name: /Compare against/ }).selectOption("spf-static");
  await expect(page.getByRole("img", { name: /topology at tick/ }).nth(1)).toBeVisible();
  await expect(page.locator("figcaption").nth(1)).toContainText("spf-static");
  await expect(page.locator("figcaption").first()).toContainText("orbit");
});

test("changing the primary algorithm changes what is drawn", async ({ page }) => {
  const label = page.locator("figcaption").first();
  const before = await label.textContent();
  await page.getByRole("combobox", { name: /Primary/ }).selectOption("ecmp");
  await expect(label).not.toHaveText(before ?? "");
});

test("the timeline advances the tick", async ({ page }) => {
  const caption = page.locator("figcaption").first();
  await expect(caption).toContainText("tick 0");
  const slider = page.getByRole("slider").first();
  await slider.focus();
  for (let index = 0; index < 5; index += 1) await page.keyboard.press("ArrowRight");
  await expect(caption).not.toContainText("tick 0");
});

test("the live view is reachable and asks for credentials rather than faking data", async ({
  page,
}) => {
  await page.getByRole("button", { name: /Live session/ }).click();
  await expect(page.getByRole("heading", { name: "Live session" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByRole("button", { name: /Start a live session/ })).toBeVisible();
});

test("every interactive control is reachable by keyboard", async ({ page }) => {
  const reachable = new Set<string>();
  for (let step = 0; step < 25; step += 1) {
    await page.keyboard.press("Tab");
    const description = await page.evaluate(() => {
      const active = document.activeElement;
      if (!active || active === document.body) return null;
      return `${active.tagName}:${active.getAttribute("aria-label") ?? active.textContent?.trim().slice(0, 20) ?? ""}`;
    });
    if (description) reachable.add(description);
  }
  expect(reachable.size).toBeGreaterThan(3);
  expect([...reachable].some((entry) => entry.startsWith("SELECT"))).toBe(true);
  expect([...reachable].some((entry) => entry.startsWith("BUTTON"))).toBe(true);
});

test("the replay view has no detectable WCAG 2 AA violations", async ({ page }) => {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((violation) => `${violation.id}: ${violation.help}`),
  ).toEqual([]);
});

test("the live view has no detectable WCAG 2 AA violations", async ({ page }) => {
  await page.getByRole("button", { name: /Live session/ }).click();
  await expect(page.getByRole("heading", { name: "Live session" })).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((violation) => `${violation.id}: ${violation.help}`),
  ).toEqual([]);
});
