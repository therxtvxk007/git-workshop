import { expect, test } from "@playwright/test";
import { asPeerReviewer, asReviewer } from "./fixtures";

/**
 * The blinded two-reviewer workflow.
 *
 * This is the spec that matters most, because blinding is the claim that is
 * easiest to make and hardest to keep. It asserts on what a second reviewer can
 * actually read on screen before and after submitting, not on whether a
 * component was rendered with the right prop.
 */
test.describe("blinded review", () => {
  const firstRationale =
    "Two independent clusters support the claim and nothing contradicts it before the cutoff.";
  const secondRationale =
    "One supporting item is a rewrite of another, so the independent support is thinner than it looks.";

  test("a reviewer cannot see the model's opinion or a peer's answer before submitting", async ({ page }) => {
    await asReviewer(page);
    await page.goto("/review");
    await page.locator("table tbody tr a").first().click();
    await expect(page).toHaveURL(/\/review\//);

    await expect(page.getByText("Blinded", { exact: true })).toBeVisible();
    // The model's numbers are absent from the payload, so they cannot appear.
    await expect(page.getByRole("heading", { name: "Peer reviews" })).toHaveCount(0);
    await expect(page.getByText(/Calibrated probability/)).toHaveCount(0);

    await page.getByRole("radio", { name: /Accept/ }).check();
    await page.locator("#review-rationale").fill(firstRationale);
    await page.getByRole("button", { name: /Submit review/ }).click();

    await expect(page.getByText("Submitted — immutable")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Peer reviews" })).toBeVisible();
  });

  test("a submitted review cannot be edited, only adjudicated", async ({ page }) => {
    await asReviewer(page);
    await page.goto("/review");
    await page.locator("table tbody tr a").first().click();
    const taskUrl = page.url();

    await page.getByRole("radio", { name: /Accept/ }).check();
    await page.locator("#review-rationale").fill(firstRationale);
    await page.getByRole("button", { name: /Submit review/ }).click();
    await expect(page.getByText("Submitted — immutable")).toBeVisible();

    // Reopening offers no edit path at all: the form is gone, not disabled.
    await page.goto(taskUrl);
    await expect(page.locator("#review-rationale")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Submit review/ })).toHaveCount(0);
  });

  test("the second reviewer is unblinded only by their own submission", async ({ page }) => {
    await asReviewer(page);
    await page.goto("/review");
    await page.locator("table tbody tr a").first().click();
    const taskUrl = page.url();
    await page.getByRole("radio", { name: /Accept/ }).check();
    await page.locator("#review-rationale").fill(firstRationale);
    await page.getByRole("button", { name: /Submit review/ }).click();
    await expect(page.getByText("Submitted — immutable")).toBeVisible();

    await asPeerReviewer(page);
    await page.goto(taskUrl);
    await expect(page.getByText(firstRationale)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Peer reviews" })).toHaveCount(0);

    await page.getByRole("radio", { name: /Correct/ }).check();
    await page.locator("#review-rationale").fill(secondRationale);
    await page.getByRole("button", { name: /Submit review/ }).click();

    await expect(page.getByRole("heading", { name: "Peer reviews" })).toBeVisible();
    await expect(page.getByText(firstRationale)).toBeVisible();
    // Two different decisions, so the escalation path opens.
    await expect(page.getByRole("button", { name: "Raise dispute" })).toBeVisible();
  });

  test("submission is refused until a rationale is given", async ({ page }) => {
    await asReviewer(page);
    await page.goto("/review");
    await page.locator("table tbody tr").nth(1).locator("a").click();
    await page.getByRole("radio", { name: /Accept/ }).check();
    await expect(page.getByRole("button", { name: /Submit review/ })).toBeDisabled();
    await page.locator("#review-rationale").fill("Too short");
    await expect(page.getByRole("button", { name: /Submit review/ })).toBeDisabled();
    await page.locator("#review-rationale").fill(firstRationale);
    await expect(page.getByRole("button", { name: /Submit review/ })).toBeEnabled();
  });
});
