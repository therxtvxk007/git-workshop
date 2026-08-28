import { expect, test } from "@playwright/test";
import { asAnalyst } from "./fixtures";

test.describe("district detail", () => {
  test.beforeEach(async ({ page }) => {
    await asAnalyst(page);
    await page.locator("table tbody tr a").first().click();
    await expect(page).toHaveURL(/\/forecasts\//);
  });

  test("frames the probability as a horizon claim, not a statement about today", async ({ page }) => {
    await expect(page.getByText(/statement about the 30 days following the cutoff/i)).toBeVisible();
  });

  test("shows raw beside calibrated so the identity calibration is visible", async ({ page }) => {
    await expect(page.getByText("Raw", { exact: true })).toBeVisible();
    await expect(page.getByText("Calibrated", { exact: true })).toBeVisible();
    await expect(page.getByText(/identity@uncalibrated/).first()).toBeVisible();
  });

  test("every chart offers its numbers as a table", async ({ page }) => {
    await page.getByRole("button", { name: /show data table/i }).first().click();
    await expect(page.locator("figure table")).toBeVisible();
    await expect(page.getByText(/not yet scoreable|occurred|no outcome recorded/).first()).toBeVisible();
  });

  test("provenance is copyable rather than retypable", async ({ page }) => {
    await expect(page.getByTitle(/Copy snapshot/)).toBeVisible();
    await expect(page.getByTitle(/Copy run/)).toBeVisible();
    await expect(page.getByTitle(/Copy config/)).toBeVisible();
  });

  test("attribution carries its caveat above the chart, not in a tooltip", async ({ page }) => {
    await expect(page.getByText("How to read this")).toBeVisible();
    await expect(page.getByText(/not a causal claim about the district/i)).toBeVisible();
  });
});
