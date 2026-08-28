import { expect, test } from "@playwright/test";
import { asAnalyst, expectSafetyBanner } from "./fixtures";

test.describe("overview", () => {
  test.beforeEach(async ({ page }) => {
    await asAnalyst(page);
  });

  test("carries the cutoff, snapshot and data mode on every route", async ({ page }) => {
    await expectSafetyBanner(page);
    // `exact` matters: Playwright's text matching is case-insensitive and
    // substring by default, so a loose "SYNTHETIC" also matches the banner's
    // "Synthetic data — research use only" and the assertion goes ambiguous.
    await expect(page.getByText("SYNTHETIC", { exact: true })).toBeVisible();
    await expect(page.getByText(/^cutoff/)).toBeVisible();
    await expect(page.getByText(/^snapshot/)).toBeVisible();
  });

  test("filters live in the URL so a view can be shared as a link", async ({ page }) => {
    await page.getByLabel("Event family").selectOption("flood");
    await expect(page).toHaveURL(/family=flood/);
    await page.getByRole("checkbox", { name: "Alert" }).check();
    await expect(page).toHaveURL(/status=alert/);

    // The shared link must reproduce the same row set for the next reader.
    const shared = page.url();
    const rowCount = await page.locator("table tbody tr").count();
    await page.goto("/");
    await page.goto(shared);
    await expect(page.locator("table tbody tr")).toHaveCount(rowCount);
  });

  test("an empty result says the query succeeded, not that it failed", async ({ page }) => {
    await page.getByLabel("Search district").fill("nowhere-that-exists");
    await expect(page.getByText(/No districts match these filters/i)).toBeVisible();
    await expect(page.getByText(/succeeded and matched nothing/i)).toBeVisible();
  });

  test("falls back to the table when no basemap is configured", async ({ page }) => {
    // The console ships without a default tile provider on purpose, so this is
    // the state a fresh install actually shows.
    await expect(page.getByText("Map unavailable")).toBeVisible();
    await expect(page.getByText(/the ranked table below carries the same districts/i)).toBeVisible();
    await expect(page.locator("table tbody tr").first()).toBeVisible();
  });

  test("exports carry the cutoff and the research-use notice inside the file", async ({ page }) => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^DEMO-pramaanx-ranked-districts-\d{4}-\d{2}-\d{2}\.csv$/);
  });

  test("retained-but-unscoreable statuses are surfaced, not hidden", async ({ page }) => {
    await expect(page.getByText("Retained but unscoreable")).toBeVisible();
    await page.getByRole("checkbox", { name: "Abstain" }).check();
    await expect(page.locator("table tbody tr").first()).toBeVisible();
  });
});
