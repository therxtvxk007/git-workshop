import { expect, type Page } from "@playwright/test";

/**
 * Shared helpers for the end-to-end specs.
 *
 * The specs run against the mock adapter and the local cloud backend, which is
 * the only configuration that is fully deterministic: the demo dataset is built
 * from a fixed seed, so a spec that asserts on a specific district still passes
 * next month.
 */

export const DEMO_PASSWORD = "demo";

export async function signIn(page: Page, email: string) {
  await page.goto("/");
  const signOut = page.getByRole("button", { name: "Sign out" });
  if (await signOut.count()) {
    await signOut.first().click();
  }
  await page.goto("/auth");
  await page.locator("#auth-email").fill(email);
  await page.locator("#auth-password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/auth/);
}

export const asAdmin = (page: Page) => signIn(page, "admin@demo.invalid");
export const asAnalyst = (page: Page) => signIn(page, "analyst@demo.invalid");
export const asReviewer = (page: Page) => signIn(page, "reviewer@demo.invalid");
export const asPeerReviewer = (page: Page) => signIn(page, "peer@demo.invalid");

/** The banner must be on every route. A page without it is a bug, not a style. */
export async function expectSafetyBanner(page: Page) {
  await expect(page.getByText(/RESEARCH USE ONLY/i).first()).toBeVisible();
}
