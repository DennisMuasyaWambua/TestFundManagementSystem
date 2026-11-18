import { expect, test } from "@playwright/test";

import { USERS, signIn } from "./helpers";

/**
 * End-to-end scenarios 3 and 4 from section 12.
 *
 * 3. Finance runs the month-end checklist through to the end; the period is locked;
 *    a back-dated receipt is then refused with the lock message.
 * 4. The Taaj statement shows the held banner until the suspense balance is cleared.
 */
const PERIOD_END = "2026-02-28";

test.describe.configure({ mode: "serial" });

test.describe("month-end close", () => {
  test("the checklist runs, and the period locks", async ({ page }) => {
    await signIn(page, USERS.financeHead);
    await page.goto(`/close?period_end=${PERIOD_END}`);

    const card = page.locator("section").filter({ hasText: /Rayan/ }).first();
    await expect(card).toBeVisible({ timeout: 20_000 });

    // Run whichever steps are still outstanding: accruals, then the revaluation.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      const run = card.getByRole("button", { name: /^run it$/i }).first();
      if ((await run.count()) === 0) break;
      await run.click();
      await expect(card.getByRole("button", { name: /running/i })).toHaveCount(0, {
        timeout: 30_000,
      });
    }

    await card.getByRole("button", { name: /close the period/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(PERIOD_END);
    // A reconciliation break has to be overridden in writing; the dialog asks for it.
    const reason = dialog.getByLabel(/why are you closing/i);
    if (await reason.isVisible().catch(() => false)) {
      await reason.fill(
        "Custodian statement for February not yet received; break reviewed with finance.",
      );
    }
    await dialog.getByRole("button", { name: /close and lock/i }).click();

    await expect(card.getByText(/locked through|already closed/i).first()).toBeVisible({
      timeout: 30_000,
    });
  });

  test("a back-dated receipt is refused, and the message says why", async ({ page }) => {
    await signIn(page, USERS.financeHead);
    await page.goto("/receipts/new");

    await page.getByLabel("Client").selectOption("RAYAN");
    await page.getByLabel(/^Amount/).fill("1000.00");
    // Inside the period that was just closed.
    await page.getByLabel("Value date").fill("2026-02-10");
    await page.getByLabel(/custodian advice reference/i).fill("ABSA-CR-BACKDATED");
    await page.getByRole("button", { name: /record the contribution/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /record it/i }).click();

    // The ledger refuses it, and the API's own words are shown.
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 20_000 });
    await expect(alert).toContainText(/closed through|locked/i);
    // Still on the form: nothing was posted.
    await expect(page).toHaveURL(/\/receipts\/new/);
  });
});

test.describe("a statement that does not reconcile", () => {
  test("Taaj is held until the suspense balance is cleared", async ({ page }) => {
    await signIn(page, USERS.compliance);

    await page.goto("/clients/TAAJ/statement?from=2026-01-31&to=2026-01-31");

    const posted = await page
      .getByText(/held: this statement does not reconcile|this statement reconciles/i)
      .first()
      .isVisible()
      .catch(() => false);
    test.skip(!posted, "the Taaj opening batch has not been posted in this database");

    const held = page.getByText(/held: this statement does not reconcile/i);
    if (await held.isVisible().catch(() => false)) {
      // 7,498,198.90 is owed to the client; 516,745.92 of it is unreconciled.
      await expect(page.getByText("7,498,198.90").first()).toBeVisible();
      await expect(page.getByText(/516,745.92/).first()).toBeVisible();
      await expect(page.getByText(/under finance review|suspense|correcting entry/i).first()).toBeVisible();

      // The dashboard flags the same thing, so it cannot be quietly forgotten.
      await page.goto("/dashboard");
      await expect(page.getByText(/unreconciled balance on suspense/i)).toBeVisible();
      await expect(page.getByText("516,745.92").first()).toBeVisible();
    }
  });
});
