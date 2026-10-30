import { expect, test } from "@playwright/test";
import { api, makeFood } from "./helpers";

test("a label amount in IU is 'partly counted' until the form is chosen", async ({ page }) => {
  const supp = await makeFood(page, "Multivitamin", {
    kind: "supplement", basis: "serving", serving_quantity: 1, serving_unit: "tablet",
    nutrients: { vitamin_c_mg: 60 },
    other_components: [{ name: "Vitamin A", amount: 5000, unit: "IU", nutrient_code: "vitamin_a_ug" }],
  });
  await api(page.request, "POST", "/api/log", { food_id: supp.id, quantity: 1, unit: "serving", meal: "supplement" });

  await page.goto("/");
  await expect(page.getByText(/Partly counted — \+5,000 IU from/).first()).toBeVisible();
  await page.getByRole("link", { name: `Choose form for ${supp.name}` }).first().click();
  await expect(page).toHaveURL(new RegExp(`/foods/${supp.id}#forms`));
  await page.getByRole("radio", { name: /Retinol/ }).click();
  await expect(page.getByText(/Recalculated \d+ entr/).first()).toBeVisible();

  const day = await api(page.request, "GET", "/api/summary/day");
  const vitA = day.evaluation.find((r: any) => r.code === "vitamin_a_ug");
  expect(vitA.amount).toBeGreaterThanOrEqual(1500);
  expect(day.entries.find((e: any) => e.food_id === supp.id).trust_level).toBe("user");
});
