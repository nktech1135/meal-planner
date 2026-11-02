import AxeBuilder from "@axe-core/playwright";
import { expect, request as pwRequest, test, type APIRequestContext, type Page } from "@playwright/test";
import { addDays, api, today } from "./helpers";

/*
 * Accessibility checks: axe-core (WCAG 2.0/2.1/2.2 A + AA, plus a few best-practice rules that guard the
 * page structure screen-reader users navigate by) on every page, in light and dark colour schemes, and in
 * the key opened states. Plus behaviour axe can't see: skip link, per-route titles, focus after navigation.
 */

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
// Structure rules from axe's best-practice set that matter for screen-reader navigation.
const STRUCTURE = ["page-has-heading-one", "landmark-one-main", "region", "heading-order", "landmark-unique", "landmark-no-duplicate-main", "empty-heading", "empty-table-header"];

const BASE = `http://127.0.0.1:${process.env.E2E_PORT ?? 8799}`;
const tag = Math.random().toString(36).slice(2, 6);

type Seed = { oats: any; yogurt: any; chicken: any; supp: any; recipe: any; meal: any; sharer: any };
let seed: Seed;

async function seedData(req: APIRequestContext): Promise<Seed> {
  const food = (body: Record<string, unknown>) => api(req, "POST", "/api/foods", { citation: "a11y test", ...body });
  const oats = await food({ name: `Rolled oats ${tag}`, state: "raw", nutrients: { energy_kcal: 379, protein_g: 13.2, fat_g: 6.5, carbs_g: 67.7, fiber_g: 10.1, iron_mg: 4.3 } });
  const yogurt = await food({ name: `Greek yogurt ${tag}`, brand: "Dairy Co", nutrients: { energy_kcal: 97, protein_g: 9, fat_g: 5, carbs_g: 3.9, calcium_mg: 100 } });
  const chicken = await food({ name: `Chicken breast ${tag}`, state: "raw", nutrients: { energy_kcal: 120, protein_g: 22.5, fat_g: 2.6, sodium_mg: 45 } });
  const supp = await food({
    name: `Multivitamin ${tag}`,
    kind: "supplement",
    basis: "serving",
    serving_quantity: 1,
    serving_unit: "tablet",
    nutrients: { vitamin_c_mg: 60, zinc_mg: 11 },
    other_components: [{ name: "Vitamin A", amount: 5000, unit: "IU", nutrient_code: "vitamin_a_ug" }],
  });
  await api(req, "POST", "/api/yields", { raw_food_id: chicken.id, method: "roasted", basis: "measured", raw_weight_g: 200, cooked_weight_g: 150, retention: {} });

  // Two weeks of log entries and weigh-ins, so Today, Trends and the charts have real content.
  const t = today();
  for (let i = 13; i >= 0; i--) {
    const day = addDays(t, -i);
    if (i % 5 === 3) continue; // a few unlogged days
    const at = (h: number) => `${day}T${String(h).padStart(2, "0")}:00:00Z`;
    await api(req, "POST", "/api/log", { food_id: oats.id, quantity: 60 + (i % 3) * 10, meal: "breakfast", consumed_at: at(8) });
    await api(req, "POST", "/api/log", { food_id: yogurt.id, quantity: 170, meal: "lunch", consumed_at: at(12) });
    await api(req, "POST", "/api/log", { food_id: chicken.id, quantity: 150 + i * 5, meal: "dinner", consumed_at: at(18) });
    await api(req, "POST", "/api/log", { food_id: supp.id, quantity: 1, unit: "serving", meal: "supplement", consumed_at: at(9) });
    await api(req, "PUT", `/api/body/${day}`, { weight_kg: 64 + Math.sin(i) * 0.6 - i * 0.05, body_fat_pct: null, waist_cm: null, note: "" });
  }
  await api(req, "POST", "/api/plan", { date: t, meal: "dinner", food_id: chicken.id, quantity: 180, unit: "g" });
  await api(req, "POST", "/api/plan", { date: addDays(t, 1), meal: "breakfast", food_id: oats.id, quantity: 70, unit: "g" });
  const recipe = await api(req, "POST", "/api/recipes", {
    name: `Overnight oats ${tag}`,
    servings: 2,
    cooked_weight_g: null,
    notes: "Soak overnight.",
    ingredients: [
      { food_id: oats.id, grams: 80, weighed_state: "as_is", yield_id: null, note: "" },
      { food_id: yogurt.id, grams: 200, weighed_state: "as_is", yield_id: null, note: "plain" },
    ],
  });
  const meal = await api(req, "POST", "/api/saved-meals/from-log", { name: `Usual breakfast ${tag}`, date: t, meal: "breakfast" });

  // Someone who shares their plan with the admin (who can edit it), and whom the admin shares with.
  const password = `sharer password ${tag}`;
  const { user: sharer } = await api(req, "POST", "/api/admin/users", { email: `sharer-${tag}@example.com`, display_name: `Sam ${tag}`, password });
  const other = await pwRequest.newContext({ baseURL: BASE });
  await api(other, "POST", "/api/auth/login", { email: sharer.email, password });
  const bread = await api(other, "POST", "/api/foods", { name: `Sam's bread ${tag}`, citation: "a11y test", nutrients: { energy_kcal: 250, protein_g: 9 } });
  await api(other, "POST", "/api/plan", { date: t, meal: "lunch", food_id: bread.id, quantity: 80, unit: "g" });
  await api(other, "PUT", "/api/plan-shares", { email: "admin@example.com", can_edit: true });
  await api(req, "PUT", "/api/plan-shares", { email: sharer.email, can_edit: false });
  await other.dispose();
  return { oats, yogurt, chicken, supp, recipe, meal, sharer };
}

test.beforeAll(async () => {
  const req = await pwRequest.newContext({ baseURL: BASE, storageState: "state/admin.json" });
  seed = await seedData(req);
  await req.dispose();
});

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(page.getByText(/^(Loading|Searching|Checking|Checking datasets)…$/)).toHaveCount(0);
}

/** Run axe and fail with a readable list of violations. */
async function audit(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const structure = await new AxeBuilder({ page }).withRules(STRUCTURE).analyze();
  const violations = [...results.violations, ...structure.violations];
  const report = violations
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n${v.nodes.map((n) => `    ${n.target.join(" ")} — ${n.failureSummary?.split("\n").slice(1).join("; ")}`).join("\n")}`)
    .join("\n");
  expect.soft(violations, `axe violations on ${label}:\n${report}`).toEqual([]);
}

// [name, path]; paths that need seeded ids are functions of the seed.
const pages: [string, (s: Seed) => string][] = [
  ["Today", () => "/"],
  ["Add entry", () => "/log"],
  ["Plan", () => "/plan"],
  ["Shopping list", () => "/plan/shopping"],
  ["Trends", () => "/trends?days=30"],
  ["Exercise", () => "/exercise"],
  ["Foods", () => "/foods"],
  ["Foods (online sources)", () => "/foods?tab=online"],
  ["Food detail", (s) => `/foods/${s.chicken.id}`],
  ["Supplement detail", (s) => `/foods/${s.supp.id}`],
  ["New food", () => "/foods/new"],
  ["Recipes", () => "/recipes"],
  ["Recipe", (s) => `/recipes/${s.recipe.id}`],
  ["New recipe", () => "/recipes/new"],
  ["Advisor", () => "/advisor"],
  ["Supplement check", () => "/supplements/check"],
  ["Supplement check result", (s) => `/supplements/check?food=${s.supp.id}`],
  ["Profile", () => "/profile"],
  ["Account", () => "/account"],
  ["Settings", () => "/settings"],
  ["Settings – Data", () => "/settings/data"],
  ["Settings – Users", () => "/settings/users"],
  ["Data sources & credits", () => "/about/data"],
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} scheme`, () => {
    test.use({ colorScheme: scheme });
    // The multi-step tests below audit several pages each; CI machines are slower than a laptop.
    test.describe.configure({ timeout: 120_000 });

    // One test per page, so each page has its own time budget and a failure names the page.
    for (const [name, pathOf] of pages) {
      test(`${name} passes axe`, async ({ page }) => {
        const path = pathOf(seed);
        await page.goto(path);
        await settle(page);
        await audit(page, `${name} (${path}, ${scheme})`);
      });
    }

    test("phone-width layouts pass axe", async ({ page }) => {
      await page.setViewportSize({ width: 412, height: 915 });
      for (const path of ["/", "/log", "/plan", "/trends?days=7", "/advisor", "/foods", "/settings", `/supplements/check?food=${seed.supp.id}`, `/plan?of=${seed.sharer.id}`]) {
        await test.step(path, async () => {
          await page.goto(path);
          await settle(page);
          await audit(page, `${path} at phone width (${scheme})`);
        });
      }
      // The plan's day tabs only exist at phone width.
      await page.goto("/plan");
      await settle(page);
      const tab = page.getByRole("tab", { selected: true });
      await tab.focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("tab", { selected: true })).toBeFocused();
      await expect(page.getByRole("tabpanel")).toBeVisible();
      await audit(page, `plan day tabs (${scheme})`);
    });

    test("signed-out pages pass axe", async ({ browser }) => {
      const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] }, colorScheme: scheme });
      const page = await ctx.newPage();
      await page.goto("/");
      await settle(page);
      await audit(page, `sign in (${scheme})`);
      await page.getByRole("tab", { name: "Create account" }).click();
      await audit(page, `create account (${scheme})`);
      await page.getByRole("tab", { name: "Sign in" }).click();
      await page.getByRole("button", { name: "Forgot password?" }).click();
      await audit(page, `forgot password (${scheme})`);
      await page.goto("/reset-password?token=not-a-real-token");
      await settle(page);
      await audit(page, `reset password (${scheme})`);
      await ctx.close();
    });

    test("opened states pass axe", async ({ page }) => {
      await test.step("Me menu open", async () => {
        await page.goto("/");
        await settle(page);
        await page.getByRole("button", { name: /^Me\b/ }).click();
        await expect(page.getByRole("link", { name: "Profile" })).toBeVisible();
        await audit(page, "Me menu open");
      });
      await test.step("entry editor open and all nutrients shown", async () => {
        await page.goto("/");
        await settle(page);
        await page.getByRole("button", { name: `Edit ${seed.oats.name}` }).first().click();
        await expect(page.getByRole("form", { name: `Edit ${seed.oats.name}` })).toBeVisible();
        await page.getByRole("button", { name: /^Show all nutrients/ }).click();
        await audit(page, "entry editor open");
      });
      await test.step("copy-day and save-meal forms open", async () => {
        await page.goto("/");
        await settle(page);
        await page.getByRole("button", { name: "Copy day to…" }).click();
        await page.getByRole("button", { name: /^Save as meal…/ }).first().click();
        await audit(page, "copy/save forms open");
      });
      await test.step("barcode scanner open", async () => {
        await page.goto("/log");
        await settle(page);
        await page.getByRole("button", { name: "Scan barcode" }).click();
        const scanner = page.getByRole("region", { name: "Scan a barcode" });
        await expect(scanner.getByText(/Type the number instead/)).toBeVisible();
        await scanner.getByLabel("Barcode number").fill("5000000000017");
        await scanner.getByRole("button", { name: "Look up" }).click();
        await expect(scanner.getByRole("link", { name: "Add it from the label" })).toBeVisible();
        await audit(page, "barcode scanner open");
      });
      await test.step("food picked with preview", async () => {
        await page.goto("/log");
        await settle(page);
        await page.getByRole("searchbox", { name: "Search foods" }).fill(seed.yogurt.name);
        await page.locator(".pick-item").first().click();
        await expect(page.getByRole("heading", { name: "Preview" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Log it" })).toBeEnabled();
        await page.waitForLoadState("networkidle");
        await audit(page, "food picked");
      });
      await test.step("saved meals tab", async () => {
        await page.goto("/log");
        await settle(page);
        await page.getByRole("tab", { name: "Saved meals" }).click();
        await expect(page.getByRole("heading", { name: seed.meal.name })).toBeVisible();
        await audit(page, "saved meals tab");
      });
      await test.step("add-to-plan form open", async () => {
        await page.goto("/plan");
        await settle(page);
        const day = page.locator(".plan-day.is-today");
        await day.getByRole("button", { name: "+ Add to today" }).click();
        await expect(day.getByRole("form", { name: /^Add to/ })).toBeVisible();
        await audit(page, "add-to-plan open");
      });
      await test.step("plan viewed as someone else, adding to it", async () => {
        await page.goto(`/plan?of=${seed.sharer.id}`);
        await settle(page);
        await expect(page.getByRole("note", { name: "Whose plan" })).toBeVisible();
        const day = page.locator(".plan-day.is-today");
        await day.getByRole("button", { name: "+ Add to today" }).click();
        await day.getByRole("searchbox", { name: "Search foods" }).fill("bread");
        await expect(day.locator(".pick-item").first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        await audit(page, "plan of someone else");
      });
      await test.step("shopping list of someone else", async () => {
        await page.goto(`/plan/shopping?of=${seed.sharer.id}`);
        await settle(page);
        await audit(page, "shopping list of someone else");
      });
      await test.step("sharing section open", async () => {
        await page.goto("/plan");
        await settle(page);
        await page.getByText("Share your plan").click();
        await expect(page.getByRole("heading", { name: "Plans shared with you" })).toBeVisible();
        const form = page.getByRole("form", { name: "Share your plan" });
        await form.getByLabel("Share with (email)").fill("nobody-at-all@example.com");
        await form.getByRole("button", { name: "Share" }).click();
        await expect(form.getByLabel("Share with (email)")).toHaveAttribute("aria-invalid", "true");
        await audit(page, "sharing section open");
      });
      await test.step("add-user form with a password, plan access open", async () => {
        await page.goto("/settings/users");
        await settle(page);
        const form = page.getByRole("region", { name: "Add a user" });
        await form.getByLabel("Set a password now").check();
        await form.getByLabel("Email").fill(`nobody-${tag}@example.com`);
        await form.getByLabel("Password", { exact: true }).fill("first password 1");
        await form.getByLabel("Confirm password").fill("other password 2");
        await form.getByRole("button", { name: "Add user" }).click();
        await expect(form.getByLabel("Confirm password")).toHaveAttribute("aria-invalid", "true");
        await page.locator("li.user-row").filter({ hasText: seed.sharer.email }).getByText("Plan access").click();
        await expect(page.getByRole("heading", { name: `Who can see Sam ${tag}'s plan` })).toBeVisible();
        await page.waitForLoadState("networkidle");
        await audit(page, "add-user form with password");
      });
      await test.step("chart tables open", async () => {
        await page.goto("/trends?days=30");
        await settle(page);
        for (const s of await page.getByText("Show as table").all()) await s.click();
        await audit(page, "chart tables open");
      });
      await test.step("retention picker open", async () => {
        await page.goto(`/foods/${seed.chicken.id}`);
        await settle(page);
        await page.getByRole("button", { name: "+ Add yield" }).click();
        await expect(page.getByRole("group", { name: /Nutrient retention/ })).toBeVisible();
        await page.waitForLoadState("networkidle");
        await audit(page, "retention picker open");
      });
      await test.step("settings secret saved", async () => {
        await page.goto("/settings");
        await settle(page);
        const usda = page.getByLabel("USDA FoodData Central API key");
        await usda.fill("abcdefgh1234WXYZ");
        await usda.locator("xpath=..").getByRole("button", { name: "Save" }).click();
        await expect(page.getByText("Set (••••••••WXYZ)")).toBeVisible();
        await audit(page, "settings secret saved");
        await api(page.request, "PUT", "/api/admin/settings", { values: { usda_fdc_api_key: null } });
      });
    });
  });
}

// ---------------------------------------------------------------------------------------------
// Behaviour axe can't check.

test("every page has one h1, landmarks and its own title", async ({ page }) => {
  test.setTimeout(120_000);
  for (const [name, pathOf] of pages) {
    const path = pathOf(seed);
    await test.step(name, async () => {
      await page.goto(path);
      await settle(page);
      await expect(page.locator("h1"), `${path}: one h1`).toHaveCount(1);
      await expect(page.getByRole("banner")).toHaveCount(1);
      await expect(page.getByRole("main")).toHaveCount(1);
      await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(1);
      await expect(page, `${path}: title`).toHaveTitle(/^.+ – Mealplan$/);
      expect(await page.title()).not.toBe("Mealplan – Mealplan");
    });
  }
  await page.goto("/trends");
  await expect(page).toHaveTitle("Trends – Mealplan");
  await page.goto(`/foods/${seed.chicken.id}`);
  await expect(page).toHaveTitle(`${seed.chicken.name} – Mealplan`);
});

test("skip link is the first Tab stop and moves focus to main", async ({ page }) => {
  await page.goto("/plan");
  await settle(page);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
});

test("route changes move focus to the new page's heading; query changes don't", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Trends" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Trends" })).toBeFocused();
  await expect(page).toHaveTitle("Trends – Mealplan");

  const week = page.getByRole("button", { name: "7 days" });
  await week.click();
  await expect(week).toBeFocused(); // a filter, not a new page

  await page.getByRole("button", { name: /^Me\b/ }).click();
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Profile" })).toBeFocused();
});

test("Me menu: Escape closes it and returns focus to the button", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  const me = page.getByRole("button", { name: /^Me\b/ });
  await me.click();
  await expect(me).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("navigation", { name: "Account" }).getByRole("link", { name: "Account" }).focus();
  await page.keyboard.press("Escape");
  await expect(me).toHaveAttribute("aria-expanded", "false");
  await expect(me).toBeFocused();
});

test("tabs follow the tab pattern (arrow keys, selection, panel)", async ({ page }) => {
  await page.goto("/log");
  await settle(page);
  const first = page.getByRole("tab", { name: "Food or supplement" });
  await expect(first).toHaveAttribute("aria-selected", "true");
  await first.focus();
  await page.keyboard.press("ArrowRight");
  const recipe = page.getByRole("tab", { name: "Recipe" });
  await expect(recipe).toBeFocused();
  await expect(recipe).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "Recipe" })).toBeVisible();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Saved meals" })).toBeFocused();
});

test("async results are announced in a live region", async ({ page }) => {
  const polite = page.locator('[data-announcer="polite"]');
  await page.goto("/log");
  await settle(page);
  await page.getByRole("searchbox", { name: "Search foods" }).fill(seed.yogurt.name);
  await expect(polite).toContainText(`1 food found for “${seed.yogurt.name}”`);
  await page.getByRole("searchbox", { name: "Search foods" }).fill("");

  await page.getByRole("button", { name: new RegExp(`^Log again ${seed.oats.name}`) }).click();
  await expect(polite).toContainText(`Logged ${seed.oats.name}`);
  const undo = page.getByRole("button", { name: new RegExp(`^Undo logging ${seed.oats.name}`) });
  await undo.click();
  await expect(polite).toContainText(`removed ${seed.oats.name}`);
  // Focus went to the notice rather than being dropped to <body>.
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
});

test("buttons keep focus while their request runs", async ({ page }) => {
  await page.goto("/profile");
  await settle(page);
  const save = page.getByRole("button", { name: "Save profile" });
  await save.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-announcer="polite"]')).toContainText("Profile saved");
  await expect(save).toBeFocused();
});

test("barcode scanner takes focus when opened and gives it back when closed", async ({ page }) => {
  await page.goto("/log");
  await settle(page);
  const open = page.getByRole("button", { name: "Scan barcode" });
  await open.click();
  const scanner = page.getByRole("region", { name: "Scan a barcode" });
  await expect(scanner.getByRole("heading", { name: "Scan a barcode" })).toBeFocused();
  await expect(scanner.getByRole("status")).toContainText(/Type the number instead|camera/i);
  await scanner.getByRole("button", { name: "Close scanner" }).click();
  await expect(open).toBeFocused();
});

test("charts have a summary, keyboard reading and a table", async ({ page }) => {
  await page.goto("/trends?days=30");
  await settle(page);
  const chart = page.getByRole("application", { name: "Energy per day" });
  await expect(chart).toHaveAccessibleDescription(/Energy per day, 30 days.*logged.*Average/);
  await chart.focus();
  await page.keyboard.press("Home");
  await expect(page.locator(".viz").first().locator("[aria-live]")).toContainText(/: (not logged|[\d,.]+ kcal)\./);
  const card = page.getByRole("region", { name: "Energy" });
  await card.getByText("Show as table").click();
  await expect(card.getByRole("table", { name: /Energy per day/ }).getByRole("rowheader")).toHaveCount(30);
});

test("password mismatch is reported on the field and focused", async ({ page }) => {
  await page.goto("/account");
  await settle(page);
  await page.getByLabel("Current password").fill("whatever password");
  await page.getByLabel("New password", { exact: true }).fill("new password 123");
  await page.getByLabel("Confirm new password").fill("new password 456");
  await page.getByRole("button", { name: "Change password" }).click();
  const confirm = page.getByLabel("Confirm new password");
  await expect(confirm).toBeFocused();
  await expect(confirm).toHaveAttribute("aria-invalid", "true");
  await expect(confirm).toHaveAccessibleDescription("The passwords don't match.");
});
