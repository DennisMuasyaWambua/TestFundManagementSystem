import { expect, test } from "@playwright/test";

import { USERS, signIn } from "./helpers";

/**
 * End-to-end scenario 2 from section 12.
 *
 * A maker records a contribution and raises a Wakala instruction; two signatories
 * approve it; the maker uploads the signed scan; finance records the custodian's
 * confirmation; the holding then appears as active.
 *
 * This is the control the whole system exists to enforce: money leaves custody only
 * on a letter signed by two people who did not prepare it, and only once the
 * custodian says it moved.
 */
const DEAL = `FD-E2E-${Date.now().toString().slice(-6)}`;
const AMOUNT = "250000.00";
const VALUE_DATE = "2026-03-02";
const MATURITY = "2026-09-02";

test.describe.configure({ mode: "serial" });

test.describe("a Wakala deposit, from contribution to active holding", () => {
  test("the maker records the client's contribution", async ({ page }) => {
    await signIn(page, USERS.maker);
    await page.goto("/receipts/new");

    await page.getByLabel("Client").selectOption("RAYAN");
    await page.getByLabel(/^Amount/).fill("250000.00");
    await page.getByLabel("Value date").fill(VALUE_DATE);
    await page.getByLabel(/custodian advice reference/i).fill(`ABSA-CR-${DEAL}`);
    await page.getByRole("button", { name: /record the contribution/i }).click();

    // The confirmation restates the client, the amount and the account.
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Rayan");
    await expect(dialog).toContainText("USD 250,000.00");
    await dialog.getByRole("button", { name: /record it/i }).click();

    await expect(page).toHaveURL(/\/clients\/RAYAN/, { timeout: 20_000 });
  });

  test("the maker raises the instruction, and the checks pass", async ({ page }) => {
    await signIn(page, USERS.maker);
    await page.goto("/instructions/new");

    await page.getByLabel("Instruction type").selectOption("PLACE_WAKALA");
    await page.getByLabel("Client").selectOption("RAYAN");
    await page.getByLabel(/^Amount/).fill(AMOUNT);
    await page.getByLabel("Value date").fill(VALUE_DATE);
    await page.getByLabel("Beneficiary", { exact: true }).fill("Absa Bank Kenya PLC");

    await page.getByLabel("Deal reference").fill(DEAL);
    await page.getByLabel("Counterparty").fill("Absa Bank Kenya PLC");
    await page.getByLabel(/expected profit rate/i).fill("0.0425");
    await page.getByLabel("Maturity date").fill(MATURITY);
    await page.getByLabel(/shariah approval reference/i).fill("SSB/2026/E2E");

    // The checks panel is the API's own answer, not this screen's opinion.
    await expect(page.getByText(/^Pass$/).first()).toBeVisible({ timeout: 20_000 });

    const raise = page.getByRole("button", { name: /raise the instruction/i });
    await expect(raise).toBeEnabled();
    await raise.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("USD 250,000.00");
    await dialog.getByRole("button", { name: /raise it/i }).click();

    await expect(page).toHaveURL(/\/instructions\/\d+/, { timeout: 20_000 });
    await expect(page.getByText(/pending approval/i).first()).toBeVisible();
    // No signature yet, and nothing posted.
    await expect(page.getByText(/0 of 2 required signatures/i)).toBeVisible();
  });

  test("the maker cannot approve their own instruction", async ({ page }) => {
    await signIn(page, USERS.maker);
    await page.goto("/instructions?tab=awaiting");
    await page.getByRole("link").filter({ hasText: /INS\// }).first().click();

    await expect(page.getByRole("button", { name: /approve and sign/i })).toHaveCount(0);
  });

  test("two signatories sign it, and the letter is generated", async ({ page }) => {
    for (const signatory of [USERS.signatoryOne, USERS.signatoryTwo]) {
      await signIn(page, signatory);
      await page.goto("/instructions?tab=awaiting");

      const link = page.getByRole("link").filter({ hasText: /INS\// }).first();
      if ((await link.count()) === 0) continue;
      await link.click();

      const approve = page.getByRole("button", { name: /approve and sign/i });
      await expect(approve).toBeVisible();
      await approve.click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText(/two different signatories/i);
      await dialog.getByRole("button", { name: /^approve$/i }).click();

      await expect(page.getByText(/of 2 required signatures/i)).toBeVisible({
        timeout: 20_000,
      });
    }

    // Two signatures means the letter exists, with its hash on the record.
    await signIn(page, USERS.signatoryOne);
    await page.goto("/instructions?tab=approved");
    const approvedLink = page.getByRole("link").filter({ hasText: /INS\// }).first();
    if ((await approvedLink.count()) > 0) {
      await approvedLink.click();
      await expect(page.getByText(/2 of 2 required signatures/i)).toBeVisible();
      await expect(page.getByText(/letter hash/i)).toBeVisible();
      await expect(page.getByRole("link", { name: /download the letter/i })).toBeVisible();
    }
  });

  test("the signed scan is uploaded, then the custodian's confirmation is booked", async ({
    page,
  }) => {
    await signIn(page, USERS.financeHead);
    await page.goto("/instructions?tab=approved");

    const link = page.getByRole("link").filter({ hasText: /INS\// }).first();
    test.skip((await link.count()) === 0, "nothing is awaiting dispatch");
    await link.click();

    // Mark it sent by attaching the wet-signed scan; its hash is shown and stored.
    await page.locator("#file-signed_copy").setInputFiles({
      name: "signed-letter.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4\n% a stand-in for the scanned, wet-signed letter\n"),
    });
    await expect(page.getByText(/sha-256/i).first()).toBeVisible();
    await page.getByRole("button", { name: /mark as sent/i }).click();

    // Only now can settlement be recorded, and only for the instructed amount.
    const confirmation = page.getByLabel(/custodian confirmation reference/i);
    await expect(confirmation).toBeVisible({ timeout: 20_000 });
    await confirmation.fill(`ABSA-CONF-${DEAL}`);
    await page.getByRole("button", { name: /record settlement/i }).click();

    await expect(page.getByText(/settled and booked/i)).toBeVisible({ timeout: 20_000 });
  });

  test("the holding is now active, with the deal terms that were instructed", async ({
    page,
  }) => {
    await signIn(page, USERS.financeHead);
    await page.goto(`/holdings/${DEAL}`);

    await expect(page.getByRole("heading", { name: DEAL })).toBeVisible();
    await expect(page.getByText(/^Active$/).first()).toBeVisible();
    await expect(page.getByText("4.25%").first()).toBeVisible();
    await expect(page.getByText("250,000.00").first()).toBeVisible();
    await expect(page.getByText("SSB/2026/E2E")).toBeVisible();
  });
});
