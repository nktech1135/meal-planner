import { expect, test, type Page } from "@playwright/test";
import { api, makeFood } from "./helpers";

const PAGES = ["/", "/log", "/plan", "/plan/shopping", "/trends", "/foods", "/foods/new", "/supplements/check", "/recipes", "/advisor", "/about/data",
  "/profile", "/account", "/settings", "/settings/data", "/settings/users"];

async function noSidewaysScroll(page: Page, path: string) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 4\d\d/.test(m.text())) errors.push(m.text());
  });
  page.on("response", (r) => {
    if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`);
  });
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main, #root").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal overflow (px)").toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
}

for (const path of PAGES) {
  test(`${path} renders without errors or sideways scrolling`, async ({ page }) => noSidewaysScroll(page, path));
}

test("a supplement check result renders without errors or sideways scrolling", async ({ page }) => {
  const supp = await makeFood(page, "Layout multivitamin with a rather long product name", {
    kind: "supplement", basis: "serving", serving_quantity: 1, serving_unit: "tablet",
    nutrients: { vitamin_c_mg: 60, magnesium_mg: 400, zinc_mg: 11 },
    other_components: [{ name: "Vitamin A", amount: 5000, unit: "IU", nutrient_code: "vitamin_a_ug" }, { name: "Green tea extract", amount: 200, unit: "mg" }],
  });
  await noSidewaysScroll(page, `/supplements/check?food=${supp.id}`);
  await expect(page.getByRole("heading", { level: 2, name: /^Result for / })).toBeVisible();
});

test("a plan shared with you, its shopping list and plan access render without sideways scrolling", async ({ page, browser }) => {
  const t = Math.random().toString(36).slice(2, 7);
  const password = `layout sharer ${t}`;
  const { user } = await api(page.request, "POST", "/api/admin/users", {
    email: `layout-sharer-with-a-long-address-${t}@example.com`, display_name: `Someone with a fairly long name ${t}`, password,
  });
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  await api(ctx.request, "POST", "/api/auth/login", { email: user.email, password });
  await api(ctx.request, "PUT", "/api/plan-shares", { email: "admin@example.com", can_edit: true });
  await ctx.close();
  await noSidewaysScroll(page, `/plan?of=${user.id}`);
  await expect(page.getByRole("note", { name: "Whose plan" })).toBeVisible();
  await noSidewaysScroll(page, `/plan/shopping?of=${user.id}`);
  await noSidewaysScroll(page, "/plan");
  await page.getByText("Share your plan").click();
  await expect(page.getByRole("heading", { name: "Plans shared with you" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await noSidewaysScroll(page, "/settings/users");
  await page.getByLabel("Set a password now").check();
  await page.locator("li.user-row").filter({ hasText: user.email }).getByText("Plan access").click();
  await expect(page.getByRole("heading", { name: /^Who can see Someone/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});
