import { expect, test, type Page } from "@playwright/test";
import { makeFood } from "./helpers";

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
