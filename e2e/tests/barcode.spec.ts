import { expect, test } from "@playwright/test";
import { makeFood } from "./helpers";

test("type a barcode when there's no camera, pick the product, and log it", async ({ page }) => {
  const code = `4${Date.now().toString().slice(-11)}`;
  const food = await makeFood(page, "Bakery rye", { barcode: code, ingredients: "Rye flour, water, salt" });

  await page.goto("/log");
  await page.getByRole("button", { name: "Scan barcode" }).click();
  const scanner = page.getByRole("region", { name: "Scan a barcode" });
  await expect(scanner.getByText(/Type the number instead/)).toBeVisible(); // headless: no camera
  await scanner.getByLabel("Barcode number").fill(`0${code}`);
  await scanner.getByRole("button", { name: "Look up" }).click();
  await expect(scanner.getByText(/in this app's database/)).toBeVisible();
  await scanner.getByRole("button", { name: new RegExp(food.name) }).click();
  await expect(page.getByLabel("Amount")).toBeVisible();
});

test("an unknown barcode offers to add the product with the barcode filled in", async ({ page }) => {
  await page.goto("/log");
  await page.getByRole("button", { name: "Scan barcode" }).click();
  const scanner = page.getByRole("region", { name: "Scan a barcode" });
  await scanner.getByLabel("Barcode number").fill("5000000000017");
  await scanner.getByRole("button", { name: "Look up" }).click();
  await scanner.getByRole("link", { name: "Add it from the label" }).click();
  await expect(page).toHaveURL(/\/foods\/new\?barcode=5000000000017/);
  await expect(page.getByRole("textbox", { name: /^Barcode(?! number)/ })).toHaveValue("5000000000017");
});
