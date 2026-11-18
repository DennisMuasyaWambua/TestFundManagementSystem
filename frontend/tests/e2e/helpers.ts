import { expect, type Page } from "@playwright/test";

/** The seeded users from `scripts/seed.py`, by the role each scenario needs. */
export const USERS = {
  maker: "ops.maker",
  signatoryOne: "sig.one",
  signatoryTwo: "sig.two",
  financeHead: "fin.head",
  financeOfficer: "fin.officer",
  compliance: "compliance",
  admin: "admin",
} as const;

/** The password CI seeds every user with. */
export const SEED_PASSWORD = process.env.FMS_SEED_PASSWORD ?? "E2e-Seeded-Pass-1!";

/**
 * Sign in as a seeded user.
 *
 * Seeded accounts start with a temporary password and MFA not yet enrolled, so the
 * sign-in is one step: the authenticator step appears only once a user in an
 * MFA-required role has actually enrolled. First sign-in lands on the profile page
 * to change the password, which the scenarios step past.
 */
export async function signIn(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(SEED_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/(dashboard|settings\/profile)/, { timeout: 20_000 });
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** Read a figure out of the page and compare it as a string, never as a number. */
export async function expectAmountVisible(page: Page, formatted: string): Promise<void> {
  await expect(page.getByText(formatted, { exact: false }).first()).toBeVisible();
}
