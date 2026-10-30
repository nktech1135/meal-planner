import { expect, test } from "@playwright/test";
import { api, makeFood, today } from "./helpers";

test("plan a food, log it from the plan, see it on the shopping list", async ({ page }) => {
  const food = await makeFood(page, "Lentils", { nutrients: { energy_kcal: 116, protein_g: 9 } });
  await page.goto("/plan");
  const day = page.locator(".plan-day.is-today");
  await day.getByRole("button", { name: "+ Add to today" }).click();
  const form = day.getByRole("form", { name: /^Add to/ });
  await form.getByLabel("Meal").selectOption("dinner");
  await form.getByRole("searchbox", { name: "Search foods" }).fill(food.name);
  await form.locator(".pick-item").first().click();
  await form.getByLabel("Amount").fill("180");
  await form.getByRole("button", { name: "Add to plan" }).click();
  await expect(day.getByText(new RegExp(`Added ${food.name}`))).toBeVisible();

  const plan = await api(page.request, "GET", `/api/plan?start=${today()}&end=${today()}`);
  const item = plan[0].items.find((i: any) => i.food_id === food.id);
  expect(item.quantity).toBe(180);

  await page.goto(`/plan/shopping`);
  await expect(page.getByText(food.name).first()).toBeVisible();

  await api(page.request, "POST", `/api/plan/${item.id}/log`);
  const entries = (await api(page.request, "GET", "/api/summary/day")).entries;
  expect(entries.some((e: any) => e.food_id === food.id && e.quantity === 180)).toBe(true);
});
