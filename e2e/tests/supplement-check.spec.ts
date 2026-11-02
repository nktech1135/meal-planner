import { expect, request as pwRequest, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { addDays, api, today } from "./helpers";

/*
 * Supplement check, on its own account so the numbers are known: five logged days of one diet food, a calcium
 * supplement and a calming blend taken daily, and a multivitamin that isn't taken yet.
 */

const BASE = `http://127.0.0.1:${process.env.E2E_PORT ?? 8799}`;
const tag = Math.random().toString(36).slice(2, 7);
const NAMES = { calcium: `Calcium 600 ${tag}`, calm: `Calm blend ${tag}`, multi: `Daily multi ${tag}` };

type Ids = { diet: number; calcium: number; calm: number; multi: number };
let ids: Ids;
let storage: Awaited<ReturnType<APIRequestContext["storageState"]>>;

async function seed(req: APIRequestContext): Promise<Ids> {
  await api(req, "PUT", "/api/profile", {
    sex: "male", birth_date: "1985-01-01", height_cm: 180, weight_kg: 80, activity_level: "moderate", goal: "maintain", timezone: "UTC",
  });
  const food = (body: Record<string, unknown>) => api(req, "POST", "/api/foods", { citation: "e2e test", ...body });
  const supp = (body: Record<string, unknown>) => food({ kind: "supplement", basis: "serving", serving_quantity: 1, serving_unit: "tablet", ...body });
  const diet = await food({ name: `Usual diet ${tag}`, nutrients: { energy_kcal: 270, vitamin_c_mg: 40, iron_mg: 0.4, calcium_mg: 50, magnesium_mg: 20 } });
  const calcium = await supp({ name: NAMES.calcium, nutrients: { calcium_mg: 600 } });
  const calm = await supp({ name: NAMES.calm, nutrients: {}, other_components: [{ name: "Ashwagandha root extract", amount: 150, unit: "mg" }] });
  const multi = await supp({
    name: NAMES.multi,
    nutrients: { vitamin_c_mg: 100, iron_mg: 18, calcium_mg: 200, magnesium_mg: 250, vitamin_d_ug: 25, biotin_ug: 2 },
    other_components: [
      { name: "Ashwagandha Root Extract", amount: 300, unit: "mg" },
      { name: "Vitamin A", amount: 5000, unit: "IU", nutrient_code: "vitamin_a_ug" },
    ],
  });
  for (let d = 1; d <= 5; d++) {
    const at = `${addDays(today(), -d)}T12:00:00Z`;
    await api(req, "POST", "/api/log", { food_id: diet.id, quantity: 1000, unit: "g", meal: "lunch", consumed_at: at }); // 2,700 kcal
    await api(req, "POST", "/api/log", { food_id: calcium.id, quantity: 1, unit: "serving", meal: "supplement", consumed_at: at });
    await api(req, "POST", "/api/log", { food_id: calm.id, quantity: 1, unit: "serving", meal: "supplement", consumed_at: at });
  }
  return { diet: diet.id, calcium: calcium.id, calm: calm.id, multi: multi.id };
}

test.beforeAll(async () => {
  const req = await pwRequest.newContext({ baseURL: BASE });
  const resp = await req.post("/api/auth/register", { data: { email: `supp-${tag}@example.com`, password: "supplement check 123", display_name: "Supp" } });
  expect(resp.status(), await resp.text()).toBe(201);
  ids = await seed(req);
  storage = await req.storageState();
  await req.dispose();
});

async function userPage(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext({ storageState: storage });
  return ctx.newPage();
}

const row = (page: Page, nutrient: string) =>
  page.locator("table.check-table tr", { has: page.getByRole("rowheader", { name: nutrient, exact: true }) });

test("lists the supplements you take, each checked against the rest", async ({ browser }) => {
  const page = await userPage(browser);
  await page.goto("/supplements/check");
  await expect(page.getByRole("heading", { level: 1, name: "Supplement check" })).toBeVisible();
  const stack = page.getByRole("region", { name: "Your supplements" });
  const calcium = stack.getByRole("listitem").filter({ has: page.getByRole("heading", { name: NAMES.calcium }) });
  await expect(calcium).toContainText("Fills gaps");
  await expect(calcium).toContainText("Fills gaps in Calcium.");
  await expect(calcium).toContainText("Taken on 5 of 5 logged days · usually 1 serving a day");
  const calm = stack.getByRole("listitem").filter({ has: page.getByRole("heading", { name: NAMES.calm }) });
  await expect(calm).toContainText("Can't tell");
  await expect(stack.getByRole("heading", { name: NAMES.multi })).toHaveCount(0);

  // Details runs the full check and moves focus to the result.
  await calcium.getByRole("button", { name: `Details for ${NAMES.calcium}` }).click();
  await expect(page.getByRole("heading", { level: 2, name: `Result for ${NAMES.calcium}` })).toBeFocused();
  await expect(row(page, "Calcium")).toContainText("Closes the gap");
  await expect(page).toHaveURL(new RegExp(`food=${ids.calcium}&days=14$`));
  await page.context().close();
});

test("checks a product picked from the database, with statuses in words and the URL kept", async ({ browser }) => {
  const page = await userPage(browser);
  await page.goto("/supplements/check");
  await page.getByRole("searchbox", { name: "Search foods" }).fill(NAMES.multi);
  await page.locator(".pick-item").filter({ hasText: NAMES.multi }).click();
  await expect(page.getByRole("group", { name: `Chosen: ${NAMES.multi}` })).toBeFocused();
  await page.getByRole("button", { name: "Check", exact: true }).click();

  const heading = page.getByRole("heading", { level: 2, name: `Result for ${NAMES.multi}` });
  await expect(heading).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`/supplements/check\\?food=${ids.multi}&days=14$`));
  const result = page.getByRole("region", { name: `Result for ${NAMES.multi}` });
  await expect(result).toContainText("Partly useful");
  await expect(result).toContainText("Fills gaps in Iron, Magnesium and Vitamin D (D2 + D3); the other 2 nutrients are already covered.");
  await expect(page.locator('[data-announcer="polite"]')).toContainText(`${NAMES.multi}: Fills gaps in Iron`);

  await expect(row(page, "Iron")).toContainText("Closes the gap");
  await expect(row(page, "Magnesium")).toContainText("Closes the gap");
  await expect(row(page, "Magnesium")).toContainText("supplements only: 250 mg with this product");
  await expect(row(page, "Vitamin D (D2 + D3)")).toContainText("Uncertain");
  await expect(row(page, "Calcium")).toContainText(`Covered by your other supplements (${NAMES.calcium})`);
  await expect(row(page, "Vitamin C")).toContainText("Already covered by food");
  await expect(row(page, "Biotin (B7)")).toContainText("Too little to matter");
  const vitA = row(page, "Vitamin A (RAE)");
  await expect(vitA).toContainText("Not counted yet");
  await expect(vitA.getByRole("link", { name: "Choose the form of Vitamin A" })).toHaveAttribute("href", `/foods/${ids.multi}#forms`);
  await expect(page.getByRole("table", { name: /^Nutrients in / }).getByRole("rowheader")).toHaveCount(7);

  const other = page.getByRole("region", { name: "Other ingredients" });
  await expect(other).toContainText("Ashwagandha Root Extract — 300 mg");
  await expect(other).toContainText(`Also in: ${NAMES.calm} (150 mg)`);
  await expect(page.getByRole("region", { name: "What it was compared with" })).toContainText(`${NAMES.calcium} (5 days)`);
  await expect(page.getByRole("region", { name: "Keep in mind" })).toContainText("can't account for a diagnosed deficiency");

  // Reloading keeps the result.
  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: `Result for ${NAMES.multi}` })).toBeVisible();
  await expect(row(page, "Iron")).toContainText("Closes the gap");
  await page.context().close();
});

test("two servings a day go over the supplement-only magnesium limit; Back restores the usual dose", async ({ browser }) => {
  const page = await userPage(browser);
  await page.goto(`/supplements/check?food=${ids.multi}&days=14`);
  await expect(row(page, "Magnesium")).toContainText("Closes the gap");
  await page.getByLabel("Servings a day").fill("2");
  await page.getByRole("button", { name: "Check", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`food=${ids.multi}&servings=2&days=14$`));
  await expect(page.getByRole("heading", { level: 2, name: `Result for ${NAMES.multi}` })).toBeFocused();
  const mg = row(page, "Magnesium");
  await expect(mg).toContainText("Over the upper limit");
  await expect(mg).toContainText("supplements only: 500 mg with this product");
  await expect(mg).toContainText("The upper limit counts supplements only, not food.");
  await expect(page.getByText("Would take you over the upper limit for Magnesium.", { exact: true })).toBeVisible();
  await expect(page.getByText("Over an upper limit").first()).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`food=${ids.multi}&days=14$`));
  await expect(page.getByLabel("Servings a day")).toHaveValue("");
  await expect(row(page, "Magnesium")).toContainText("Closes the gap");

  // The look-back period is part of the URL too.
  await page.getByRole("button", { name: "30 days" }).click();
  await expect(page).toHaveURL(new RegExp(`food=${ids.multi}&days=30$`));
  await expect(page.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  await page.context().close();
});

test("asking the advisor fills in a question without sending it", async ({ browser }) => {
  const admin = await pwRequest.newContext({ baseURL: BASE, storageState: "state/admin.json" });
  const page = await userPage(browser);
  try {
    // Without a key the button isn't offered.
    await page.goto(`/supplements/check?food=${ids.multi}`);
    await expect(page.getByText(/isn't set up yet/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Ask the advisor about this" })).toHaveCount(0);

    await api(admin, "PUT", "/api/admin/settings", { values: { anthropic_api_key: "sk-ant-e2e-not-a-real-key" } });
    const chat: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/advisor/chat")) chat.push(r.url());
    });
    await page.goto(`/supplements/check?food=${ids.multi}&servings=2&days=14`);
    await page.getByRole("link", { name: "Ask the advisor about this" }).click();
    await expect(page).toHaveURL(/\/advisor\?ask=/);
    const box = page.getByRole("textbox", { name: "Message" });
    await expect(box).toHaveValue(
      `Is ${NAMES.multi} (food id ${ids.multi}) worth taking at 2 servings (1 tablet each) a day? Please check it against my intake over the last 14 days and my other supplements.`,
    );
    await expect(box).toHaveAccessibleDescription(/nothing is sent until you press Send/);
    await page.waitForLoadState("networkidle");
    expect(chat).toEqual([]);
    expect(await api(page.request, "GET", "/api/advisor/conversations")).toEqual([]);
  } finally {
    await api(admin, "PUT", "/api/admin/settings", { values: { anthropic_api_key: null } });
    await admin.dispose();
    await page.context().close();
  }
});

test("entry points: supplement page, Foods and hand entry", async ({ browser }) => {
  const page = await userPage(browser);
  await page.goto(`/foods/${ids.multi}`);
  await page.getByRole("link", { name: "Check if I need this" }).click();
  await expect(page).toHaveURL(new RegExp(`/supplements/check\\?food=${ids.multi}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Supplement check" })).toBeFocused();
  await expect(page.getByRole("heading", { level: 2, name: `Result for ${NAMES.multi}` })).toBeVisible();
  await expect(page.getByText("Fills gaps in Iron").first()).toBeVisible();

  // Foods (not a supplement): no such link.
  await page.goto(`/foods/${ids.diet}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Check if I need this" })).toHaveCount(0);

  await page.goto("/foods");
  await page.getByRole("link", { name: "Supplement check" }).click();
  await expect(page).toHaveURL(/\/supplements\/check$/);
  await page.getByRole("link", { name: "Enter a label by hand" }).click();
  await expect(page).toHaveURL(/\/foods\/new\?kind=supplement$/);
  await expect(page.getByLabel("Kind")).toHaveValue("supplement");
  await page.context().close();
});
