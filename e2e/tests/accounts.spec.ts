import { expect, test } from "@playwright/test";

test("admin invites someone, who sets a password from the link and signs in", async ({ page, browser }) => {
  const email = `friend-${Date.now()}@example.com`;
  await page.goto("/settings/users");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Add and create invite" }).click();
  await expect(page.getByText(new RegExp(`Created an account for ${email}`)).first()).toBeVisible();
  const link = await page.getByLabel("Set-password link").inputValue();
  expect(link).toMatch(/\/reset-password\?token=/);

  const anon = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const p = await anon.newPage();
  await p.goto(new URL(link).pathname + new URL(link).search);
  await p.getByLabel(/^New password/).fill("friend password 1");
  await p.getByLabel("Confirm password").fill("friend password 1");
  await p.getByRole("button", { name: "Set password and sign in" }).click();
  await expect(p.getByRole("heading", { name: "Today" })).toBeVisible();

  // The link is single-use.
  await p.goto(new URL(link).pathname + new URL(link).search);
  await p.getByLabel(/^New password/).fill("another password 2");
  await p.getByLabel("Confirm password").fill("another password 2");
  await p.getByRole("button", { name: "Set password and sign in" }).click();
  await expect(p.getByText(/invalid or has expired/)).toBeVisible();
  await anon.close();
});
