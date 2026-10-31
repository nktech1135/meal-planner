import { expect, test } from "@playwright/test";
import { addDays, api, makeFood, today } from "./helpers";

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

test("clear a day, then the whole week", async ({ page }) => {
  const food = await makeFood(page, "Barley");
  // A week of its own, well ahead, so other tests' plans aren't touched.
  const monday = addDays(today(), 7 * 12 - ((new Date(`${today()}T12:00:00Z`).getUTCDay() + 6) % 7));
  const tuesday = addDays(monday, 1);
  for (const date of [monday, monday, tuesday]) await api(page.request, "POST", "/api/plan", { date, food_id: food.id, quantity: 50 });
  await page.goto(`/plan?date=${monday}`);
  const mondayCard = page.locator(".plan-day").filter({ has: page.getByRole("heading", { name: /^Monday/ }) });
  await expect(mondayCard.locator("li.plan-item")).toHaveCount(2);

  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.accept();
  });
  await mondayCard.getByRole("button", { name: /^Clear day/ }).click();
  await expect(mondayCard.getByText("Cleared 2 planned items.")).toBeVisible();
  expect(dialogs[0]).toMatch(/^Remove all 2 planned items for Monday, .*\? Anything already logged stays in the food log/);
  await expect(mondayCard.getByText("Nothing planned.")).toBeVisible();

  await page.getByRole("button", { name: "Clear week" }).click();
  await expect(page.getByText("Cleared 1 planned item from this week.")).toBeVisible();
  expect(dialogs[1]).toMatch(/^Remove the 1 planned item for the week of /);
  await expect(page.getByText("Nothing is planned for this week yet.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear week" })).toHaveAttribute("aria-disabled", "true");
  expect((await api(page.request, "GET", `/api/plan?start=${monday}&end=${addDays(monday, 6)}`)).every((d: any) => d.items.length === 0)).toBe(true);
});
