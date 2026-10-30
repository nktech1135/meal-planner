import { expect, test } from "@playwright/test";
import { api } from "./helpers";

test("API keys are entered in Settings, masked, and never shown again", async ({ page }) => {
  await page.goto("/settings");
  const usda = page.getByLabel("USDA FoodData Central API key");
  await usda.fill("bad key with spaces");
  await usda.locator("xpath=..").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/must not contain spaces/)).toBeVisible();

  await usda.fill("abcdefgh1234WXYZ");
  await usda.locator("xpath=..").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Set (••••••••WXYZ)")).toBeVisible();
  const values = await page.locator("input").evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
  expect(values.some((v) => v.includes("abcdefgh"))).toBe(false);
  expect((await api(page.request, "GET", "/api/app-info")).usda_demo_key).toBe(false);

  await page.reload();
  await expect(page.getByText("Set (••••••••WXYZ)")).toBeVisible();
  await api(page.request, "PUT", "/api/admin/settings", { values: { usda_fdc_api_key: null } });
});

test("sign-ups can be closed from Settings", async ({ page, browser }) => {
  await page.goto("/settings");
  await page.getByRole("checkbox", { name: "Allow new sign-ups" }).uncheck();
  await expect.poll(async () => (await api(page.request, "GET", "/api/app-info")).allow_registration).toBe(false);

  const anon = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const p = await anon.newPage();
  await p.goto("/");
  await p.getByRole("tab", { name: "Create account" }).click();
  await expect(p.getByText("Sign-ups are closed; ask an admin for an account.")).toBeVisible();
  const refused = await p.request.post("/api/auth/register", { data: { email: "late@example.com", password: "late password 1" } });
  expect(refused.status()).toBe(403);
  await anon.close();

  await page.getByRole("checkbox", { name: "Allow new sign-ups" }).check();
  await expect.poll(async () => (await api(page.request, "GET", "/api/app-info")).allow_registration).toBe(true);
});
