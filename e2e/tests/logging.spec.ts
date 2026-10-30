import { expect, test } from "@playwright/test";
import { addDays, api, makeFood, today } from "./helpers";

test("log again from suggestions, edit an entry, copy the day", async ({ page }) => {
  const oats = await makeFood(page, "Oats", { nutrients: { energy_kcal: 380, protein_g: 13 } });
  await api(page.request, "POST", "/api/log", { food_id: oats.id, quantity: 50, meal: "breakfast" });
  const count = async (day: string) =>
    (await api(page.request, "GET", `/api/summary/day?day=${day}`)).entries.filter((e: any) => e.food_id === oats.id);

  await page.goto("/log");
  await page.getByLabel("Meal").selectOption("breakfast");
  await page.getByRole("button", { name: new RegExp(`^Log ${oats.name} again`) }).click();
  await expect(page.getByRole("status").filter({ hasText: `Logged ${oats.name}` })).toBeVisible();
  expect(await count(today())).toHaveLength(2);

  await page.goto("/");
  await page.getByRole("button", { name: `Edit ${oats.name}` }).first().click();
  const form = page.getByRole("form", { name: `Edit ${oats.name}` });
  await form.getByLabel("Amount").fill("80");
  await form.getByRole("button", { name: "Save" }).click();
  await expect.poll(async () => (await count(today())).map((e: any) => e.quantity).sort()).toEqual([50, 80]);
  const edited = (await count(today())).find((e: any) => e.quantity === 80);
  expect(edited.nutrients.energy_kcal).toBeCloseTo(304);

  await page.getByRole("button", { name: "Copy day to…" }).click();
  await page.getByLabel("Copy to day").fill(addDays(today(), 1));
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect.poll(async () => (await count(addDays(today(), 1))).length).toBeGreaterThanOrEqual(2);
});

test("saved meal: create from a logged meal and log it again", async ({ page }) => {
  const milk = await makeFood(page, "Milk", { nutrients: { energy_kcal: 60 } });
  await api(page.request, "POST", "/api/log", { food_id: milk.id, quantity: 250, meal: "snack" });
  const meal = await api(page.request, "POST", "/api/saved-meals/from-log", { name: `Snack ${milk.id}`, date: today(), meal: "snack" });

  await page.goto("/log");
  await page.getByRole("tab", { name: "Saved meals" }).click();
  const card = page.locator("li, article, section").filter({ hasText: meal.name }).last();
  await card.getByRole("button", { name: "Log", exact: true }).click();
  await expect(page.getByText(/Logged 1 item/)).toBeVisible();
});
