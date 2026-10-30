import { expect, test } from "@playwright/test";

const PAGES = ["/", "/log", "/plan", "/plan/shopping", "/trends", "/foods", "/foods/new", "/recipes", "/advisor", "/about/data",
  "/profile", "/account", "/settings", "/settings/data", "/settings/users"];

for (const path of PAGES) {
  test(`${path} renders without errors or sideways scrolling`, async ({ page }) => {
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
  });
}
