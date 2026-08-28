import { expect, test } from "@playwright/test";
import { asAnalyst } from "./fixtures";

test.describe("evidence explorer", () => {
  test.beforeEach(async ({ page }) => {
    await asAnalyst(page);
    await page.goto("/evidence");
  });

  test("counts withheld items instead of silently shortening the list", async ({ page }) => {
    await expect(page.getByText(/withheld by licence/)).toBeVisible();
  });

  test("post-cutoff evidence is opt-in and labelled when shown", async ({ page }) => {
    await expect(page.getByText("post-cutoff")).toHaveCount(0);
    await page.getByLabel(/Include evidence observed after the cutoff/).check();
    await expect(page.getByText("Post-cutoff evidence is included")).toBeVisible();
    await expect(page.getByText("post-cutoff").first()).toBeVisible();
  });

  test("opening an item deep-links to it", async ({ page }) => {
    await page.getByRole("button", { name: "Open detail" }).first().click();
    await expect(page).toHaveURL(/evidenceId=/);
    await expect(page.getByRole("dialog", { name: "Evidence detail" })).toBeVisible();
    await expect(page.getByText("Extracted span")).toBeVisible();
  });
});

test.describe("scenarios", () => {
  test("a hypothetical is never presented as a forecast", async ({ page }) => {
    await asAnalyst(page);
    await page.goto("/scenarios");
    await expect(page.getByText("Scenarios are not forecasts")).toBeVisible();

    await page.getByLabel("Baseline forecast").selectOption({ index: 1 });
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/scenarios\/.+/);

    await expect(page.getByText("Nothing on this page is a forecast")).toBeVisible();
    // Nothing hypothetical is shown until the analyst asks for it.
    await expect(page.getByText("Hypothetical (not a forecast)")).toHaveCount(0);

    await page.locator('input[type="range"]').first().fill("15");
    await page.getByRole("button", { name: /Evaluate/ }).click();
    await expect(page.getByText("Hypothetical (not a forecast)")).toBeVisible();
    await expect(page.getByText(/Would be classified/)).toBeVisible();

    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Export watermarked JSON/ }).click();
    expect((await download).suggestedFilename()).toContain("HYPOTHETICAL");
  });
});
