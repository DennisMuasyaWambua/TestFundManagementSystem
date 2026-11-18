import { expect, test } from "@playwright/test";

import { SEED_PASSWORD, USERS, signIn, signOut } from "./helpers";

/**
 * The controls that stand between a stranger and client money.
 *
 * These are checked through the browser because that is where they are relied on:
 * the API has its own tests for the same rules, and the point here is that the
 * screens actually honour the answers.
 */
test.describe("getting in, and being kept out", () => {
  test("an unauthenticated visitor is sent to sign in, and returned afterwards", async ({
    page,
  }) => {
    await page.goto("/holdings");
    await expect(page).toHaveURL(/\/login\?next=%2Fholdings/);
    await expect(page.getByRole("heading", { name: /fund management/i })).toBeVisible();

    await page.getByLabel("Username").fill(USERS.maker);
    await page.getByLabel("Password", { exact: true }).fill(SEED_PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();

    // Back to where they were headed, not dumped on the dashboard.
    await expect(page).toHaveURL(/\/(holdings|settings\/profile)/, { timeout: 20_000 });
  });

  test("the wrong password does not say which half was wrong", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill(USERS.maker);
    await page.getByLabel("Password", { exact: true }).fill("not-the-password");
    await page.getByRole("button", { name: /sign in/i }).click();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    // The message must not distinguish an unknown user from a bad password.
    await expect(alert).not.toContainText(/unknown user|no such user|wrong password/i);
  });

  test("the backend token never reaches the browser", async ({ page, context }) => {
    await signIn(page, USERS.maker);

    const cookies = await context.cookies();
    const session = cookies.find((cookie) => cookie.name === "fms_session");
    expect(session, "the session cookie should exist").toBeDefined();
    expect(session?.httpOnly, "the session cookie must be httpOnly").toBe(true);
    expect(session?.sameSite).toBe("Strict");

    // Script on the page can see the CSRF token, and nothing else.
    const visible = await page.evaluate(() => document.cookie);
    expect(visible).not.toContain("fms_session");
    expect(visible).toContain("fms_csrf");
  });

  test("signing out ends the session", async ({ page }) => {
    await signIn(page, USERS.maker);
    await page.goto("/dashboard");
    await signOut(page);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("a maker is not offered the screens their role cannot use", async ({ page }) => {
    await signIn(page, USERS.maker);
    await page.goto("/dashboard");

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Custody instructions" })).toBeVisible();
    // Month-end close, the journal, the audit log and user admin are not a maker's.
    await expect(nav.getByRole("link", { name: "Month-end close" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Audit log" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
  });

  test("navigating straight to a forbidden screen shows the API's refusal", async ({
    page,
  }) => {
    await signIn(page, USERS.maker);

    // Hiding the link is a courtesy; the API is the control. A maker who types the
    // URL must be refused, not served.
    await page.goto("/admin/users");
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/may not|not allowed|permission/i).first()).toBeVisible();
  });
});
