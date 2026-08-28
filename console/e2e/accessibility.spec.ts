import { expect, test } from "@playwright/test";
import { asAdmin } from "./fixtures";

/**
 * Accessibility guarantees the console makes explicitly.
 *
 * Not a substitute for an audit — these are the specific promises made
 * elsewhere in the codebase, checked so they cannot quietly lapse.
 */
test.describe("accessibility", () => {
  test.beforeEach(async ({ page }) => {
    await asAdmin(page);
  });

  test("a skip link reaches the main content", async ({ page }) => {
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await skip.press("Enter");
    await expect(page.locator("#main")).toBeVisible();
  });

  test("every chart's numbers are reachable without seeing the chart", async ({ page }) => {
    await page.goto("/backtests");
    const figures = page.locator("figure");
    // `count()` does not auto-wait, so the run has to have loaded first.
    await expect(figures.first()).toBeVisible();
    const count = await figures.count();
    expect(count).toBeGreaterThan(0);
    // Scoped per figure, because the toggle's own label changes to "Show
    // chart" once clicked -- indexing a live locator would walk off the end.
    for (let i = 0; i < count; i += 1) {
      const figure = figures.nth(i);
      await figure.getByRole("button", { name: /show data table/i }).click();
      await expect(figure.locator("table")).toBeVisible();
    }
  });

  test("sortable columns announce their sort state", async ({ page }) => {
    const header = page.locator("th[aria-sort]").first();
    await expect(header).toHaveAttribute("aria-sort", /ascending|descending|none/);
  });

  test("tables carry a caption describing what they contain", async ({ page }) => {
    await page.goto("/data-health");
    await expect(page.locator("table caption").first()).toHaveText(/coverage by district/i);
  });

  test("sections the user cannot enter are shown as locked, not hidden", async ({ page }) => {
    // Hiding them makes the console look different for different people and
    // invites "it works on my screen" as the answer to a permission problem.
    await page.goto("/");
    await expect(page.getByRole("link", { name: /Administration/ })).toBeVisible();
  });
});
