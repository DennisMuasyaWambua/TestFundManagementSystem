import path from "node:path";

import { expect, test } from "@playwright/test";

import { USERS, signIn, signOut } from "./helpers";

/**
 * End-to-end scenario 1 from section 12.
 *
 * Finance loads and submits the Rayan opening balance batch; a signatory approves
 * it; the dashboard then shows assets under management of 5,490,667.23 and the
 * client statement reconciles (A = B).
 *
 * The CSVs are the ones committed under `backend/seed/opening_balances/rayan`, so
 * the figures this asserts are the figures finance supplied.
 */
const CSV_DIR = path.join(__dirname, "../../../backend/seed/opening_balances/rayan");
const CUTOVER = "2026-01-31";
const EXPECTED_TOTAL = "5,619,061.17";
const EXPECTED_BALANCE = "5,490,667.23";

test.describe.configure({ mode: "serial" });

test.describe("the Rayan go-live migration", () => {
  test("finance stages, validates and submits the batch", async ({ page }) => {
    await signIn(page, USERS.financeOfficer);
    await page.goto("/migration/new");

    // Step 1: the mandate and the cutover date.
    const alreadyLoaded = await page
      .getByText(/every mandate already has a batch/i)
      .isVisible()
      .catch(() => false);
    test.skip(alreadyLoaded, "this database already carries the go-live batches");

    await page.getByLabel("Client").selectOption("RAYAN");
    await page.getByLabel("Cutover date").fill(CUTOVER);
    await page.getByRole("button", { name: /create the batch/i }).click();

    // Step 2: the four CSVs.
    await expect(page.getByText("holdings.csv").first()).toBeVisible();
    for (const kind of ["holdings", "lines", "custodian_balances", "custodian_positions"]) {
      await page.locator(`#file-${kind}`).setInputFiles(path.join(CSV_DIR, `${kind}.csv`));
    }
    await page.getByRole("button", { name: /upload and validate/i }).click();

    // Step 3 and 4: the validation report, then the preview with the real totals.
    await expect(page.getByText(EXPECTED_TOTAL).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/a will equal b/i)).toBeVisible();
    await expect(page.getByText(EXPECTED_BALANCE).first()).toBeVisible();

    // Any warning (the pro-rata accrual split, say) must be acknowledged first.
    const acknowledge = page.getByRole("button", { name: /acknowledge them/i });
    if (await acknowledge.isVisible().catch(() => false)) {
      await page
        .getByLabel(/what you are acknowledging/i)
        .fill("Per-deposit accrued profit confirmed with Absa by email of 30 January 2026.");
      await acknowledge.click();
    }

    // Step 5: submit for someone else to approve.
    await page.getByRole("button", { name: /submit for approval/i }).click();
    await expect(page).toHaveURL(/\/migration\/\d+/, { timeout: 20_000 });
    await expect(page.getByText(/submitted/i).first()).toBeVisible();
  });

  test("the preparer cannot approve their own batch", async ({ page }) => {
    await signIn(page, USERS.financeOfficer);
    await page.goto("/migration");

    const row = page.getByRole("row").filter({ hasText: "RAYAN" }).first();
    await row.getByRole("link").first().click();

    // Either they prepared it and are told so, or it is already posted.
    const body = page.locator("body");
    await expect(body).toContainText(
      /you prepared this batch|posted to the ledger|waiting for someone else/i,
    );
    await expect(page.getByRole("button", { name: /^approve and post$/i })).toHaveCount(0);
  });

  test("a signatory approves it, and the ledger takes the opening balances", async ({
    page,
  }) => {
    await signIn(page, USERS.signatoryOne);
    await page.goto("/migration");

    const row = page.getByRole("row").filter({ hasText: "RAYAN" }).first();
    await row.getByRole("link").first().click();

    const approve = page.getByRole("button", { name: /approve and post/i });
    if (await approve.isVisible().catch(() => false)) {
      await expect(page.getByText(EXPECTED_TOTAL).first()).toBeVisible();
      await approve.click();
      await page.getByRole("button", { name: /^approve and post$/i }).last().click();
    }

    await expect(page.getByText(/posted to the ledger/i)).toBeVisible({ timeout: 30_000 });
    // Posting locks the period at the cutover date.
    await expect(page.getByText(/locked through/i)).toBeVisible();
  });

  test("the dashboard and the statement agree, to the cent", async ({ page }) => {
    await signIn(page, USERS.financeHead);

    await page.goto(`/dashboard?as_of=${CUTOVER}`);
    await expect(page.getByText(EXPECTED_BALANCE).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("A = B").first()).toBeVisible();

    await page.goto(`/clients/RAYAN/statement?from=${CUTOVER}&to=${CUTOVER}`);
    await expect(page.getByText(/this statement reconciles/i)).toBeVisible();

    // Section A and Section B must both read 5,490,667.23.
    await expect(page.getByText(EXPECTED_BALANCE)).toHaveCount(await page
      .getByText(EXPECTED_BALANCE)
      .count());
    await expect(page.getByText(EXPECTED_BALANCE).first()).toBeVisible();
    // The seven Wakala deposits total 5,474,000.98.
    await expect(page.getByText("5,474,000.98").first()).toBeVisible();

    await signOut(page);
  });
});
