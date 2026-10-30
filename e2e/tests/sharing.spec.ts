import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { api, today } from "./helpers";

/*
 * Admins adding users (with a password or an invite link) and shared meal plans: one person plans
 * meals in someone else's plan, view-only access, revoking, and admins managing who sees whose plan.
 * Each person has their own browser context; the default `page` is the admin's.
 */

const tag = () => Math.random().toString(36).slice(2, 7);

type Person = { id: number; name: string; email: string; page: Page; close: () => Promise<void> };

/** Create an account (as the admin, via the API) and sign it in in a browser context of its own. */
async function person(browser: Browser, admin: APIRequestContext, first: string): Promise<Person> {
  const t = tag();
  const name = `${first} ${t}`;
  const email = `${first.toLowerCase()}-${t}@example.com`;
  const password = `${first} password ${t}`;
  const { user } = await api(admin, "POST", "/api/admin/users", { email, display_name: name, password });
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  await api(ctx.request, "POST", "/api/auth/login", { email, password });
  await api(ctx.request, "PUT", "/api/profile", { sex: "female", birth_date: "1990-01-01", height_cm: 165, weight_kg: 60, timezone: "UTC" });
  return { id: user.id, name, email, page: await ctx.newPage(), close: () => ctx.close() };
}

const food = (req: APIRequestContext, name: string) =>
  api(req, "POST", "/api/foods", { name, nutrients: { energy_kcal: 400, protein_g: 10 }, citation: "e2e test" });

test("admin adds a user with a password; they can sign in straight away", async ({ page, browser }) => {
  const t = tag();
  const email = `pw-${t}@example.com`;
  const password = `set by admin ${t}`;
  await page.goto("/settings/users");
  const form = page.getByRole("region", { name: "Add a user" });
  await form.getByLabel("Email").fill(email);
  await form.getByLabel("Name (optional)").fill(`Pat ${t}`);
  await form.getByLabel("Set a password now").check();

  // A mismatch is reported on the confirm field, which gets focus.
  await form.getByLabel("Password", { exact: true }).fill(password);
  await form.getByLabel("Confirm password").fill(`${password}x`);
  await form.getByRole("button", { name: "Add user" }).click();
  const confirm = form.getByLabel("Confirm password");
  await expect(confirm).toBeFocused();
  await expect(confirm).toHaveAttribute("aria-invalid", "true");
  await expect(confirm).toHaveAccessibleDescription("The passwords don't match.");

  await form.getByLabel("Show password").check();
  await expect(form.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
  await confirm.fill(password);
  await form.getByRole("button", { name: "Add user" }).click();
  await expect(form.getByText(`Created an account for ${email} with the password you set`)).toBeVisible();
  await expect(form.locator(".result-ok")).toContainText("Pass the password on to them; they can sign in now and change it under Account.");
  // The password isn't shown back, and the fields are cleared.
  await expect(page.locator("body")).not.toContainText(password);
  await expect(form.getByLabel("Password", { exact: true })).toHaveValue("");
  expect(await page.locator("input").evaluateAll((els, pw) => els.some((e) => (e as HTMLInputElement).value === pw), password)).toBe(false);

  const anon = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const p = await anon.newPage();
  await p.goto("/");
  await p.getByLabel("Email").fill(email);
  await p.getByLabel("Password").fill(password);
  await p.getByRole("button", { name: "Sign in" }).click();
  await expect(p.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  await anon.close();
});

test("admin adds a user with an invite link (and as an admin)", async ({ page }) => {
  const email = `invite-${tag()}@example.com`;
  await page.goto("/settings/users");
  const form = page.getByRole("region", { name: "Add a user" });
  await form.getByLabel("Email").fill(email);
  await expect(form.getByLabel("Send an invite link")).toBeChecked();
  await form.getByLabel(/^Make admin/).check();
  await form.getByRole("button", { name: "Add and create invite" }).click();
  await expect(form.getByText(`Created an account for ${email} (admin).`, { exact: false })).toBeVisible();
  expect(await form.getByLabel("Set-password link").inputValue()).toMatch(/\/reset-password\?token=/);
  const users = await api(page.request, "GET", "/api/admin/users");
  expect(users.find((u: any) => u.email === email).is_admin).toBe(true);
});

test("an editor plans meals in someone else's plan with their foods", async ({ page, browser }) => {
  test.setTimeout(60_000);
  const ann = await person(browser, page.request, "Ann");
  const ben = await person(browser, page.request, "Ben");
  const t = tag();
  const annFood = await food(ann.page.request, `Sharetest${t} granola`);
  await food(ben.page.request, `Sharetest${t} protein bar`); // Ben's own: Ann couldn't see it

  // Ann shares her plan with Ben from the Plan page.
  await ann.page.goto("/plan");
  await ann.page.getByText("Share your plan").click();
  const share = ann.page.getByRole("form", { name: "Share your plan" });
  await share.getByLabel("Share with (email)").fill(ben.email);
  await expect(share.getByLabel(/^Can edit/)).toBeChecked();
  await share.getByRole("button", { name: "Share" }).click();
  await expect(share.getByText(`${ben.name} can now see and edit your plan.`)).toBeVisible();
  await expect(ann.page.getByRole("button", { name: `Remove ${ben.name}'s access` })).toBeVisible();

  // Ben switches to Ann's plan; the choice is in the URL.
  await ben.page.goto("/plan");
  await ben.page.getByLabel("Whose plan").selectOption({ label: `${ann.name}'s plan` });
  await expect(ben.page).toHaveURL(new RegExp(`[?&]of=${ann.id}`));
  await expect(ben.page.getByRole("heading", { level: 1, name: `${ann.name}'s plan` })).toBeVisible();
  const banner = ben.page.getByRole("note", { name: "Whose plan" });
  await expect(banner).toContainText(`You're viewing ${ann.name}'s plan · you can edit it.`);
  await expect(banner).toContainText(`Only ${ann.name} can log their meals`);
  await expect(ben.page.getByRole("link", { name: "Shopping list" })).toHaveAttribute("href", new RegExp(`of=${ann.id}`));

  const day = ben.page.locator(".plan-day.is-today");
  await day.getByRole("button", { name: "+ Add to today" }).click();
  const form = day.getByRole("form", { name: /^Add to/ });
  await expect(form.getByRole("tab", { name: "Saved meal" })).toHaveCount(1); // lists the owner's saved meals
  await expect(form.getByRole("button", { name: "Scan barcode" })).toHaveCount(0);
  await form.getByRole("searchbox", { name: "Search foods" }).fill(`Sharetest${t}`);
  const results = form.getByRole("list", { name: "Food database results" });
  await expect(results.getByRole("button", { name: new RegExp(annFood.name) })).toBeVisible();
  await expect(results.getByText(/protein bar/)).toHaveCount(0);
  await results.getByRole("button", { name: new RegExp(annFood.name) }).click();
  await form.getByLabel("Meal").selectOption("lunch");
  await form.getByLabel("Amount").fill("70");
  await form.getByRole("button", { name: "Add to plan" }).click();
  await expect(day.getByText(`Added ${annFood.name}.`)).toBeVisible();
  // Logging is Ann's alone: no log buttons for Ben.
  await expect(day.getByRole("button", { name: /^Log/ })).toHaveCount(0);
  await expect(day.getByRole("button", { name: `Edit ${annFood.name}` })).toBeVisible();

  // Reloading keeps Ann's plan.
  await ben.page.reload();
  await expect(ben.page.getByRole("heading", { level: 1, name: `${ann.name}'s plan` })).toBeVisible();

  // Ann sees who added it, and can log it.
  const plan = await api(ann.page.request, "GET", `/api/plan?start=${today()}&end=${today()}`);
  expect(plan[0].items.find((i: any) => i.food_id === annFood.id)).toMatchObject({ quantity: 70, meal: "lunch", added_by: ben.name });
  await ann.page.goto("/plan");
  const annDay = ann.page.locator(".plan-day.is-today");
  await expect(annDay.getByText(`added by ${ben.name}`)).toBeVisible();
  await expect(annDay.getByRole("button", { name: `Log ${annFood.name}` })).toBeVisible();

  await ann.close();
  await ben.close();
});

test("view-only access hides editing and logging; revoking removes the plan from the selector", async ({ page, browser }) => {
  test.setTimeout(60_000);
  const cal = await person(browser, page.request, "Cal");
  const dee = await person(browser, page.request, "Dee");
  const calFood = await food(cal.page.request, `Viewonly${tag()} soup`);
  await api(cal.page.request, "POST", "/api/plan", { date: today(), meal: "dinner", food_id: calFood.id, quantity: 300, unit: "g" });
  await api(cal.page.request, "PUT", "/api/plan-shares", { email: dee.email, can_edit: false });

  await dee.page.goto("/plan");
  await expect(dee.page.getByLabel("Whose plan").locator("option", { hasText: `${cal.name}'s plan (view only)` })).toHaveCount(1);
  await dee.page.goto(`/plan?of=${cal.id}`);
  await expect(dee.page.getByRole("note", { name: "Whose plan" })).toContainText("view only");
  const day = dee.page.locator(".plan-day.is-today");
  await expect(day.getByText(calFood.name)).toBeVisible();
  await expect(dee.page.getByRole("button", { name: /^\+ Add to/ })).toHaveCount(0);
  await expect(day.getByRole("button", { name: /^(Edit|Remove|Log)/ })).toHaveCount(0);
  await expect(dee.page.getByRole("button", { name: /^Copy/ })).toHaveCount(0);
  await expect(dee.page.getByText("Share your plan")).toHaveCount(0);

  // The shopping list is readable but not tickable.
  await dee.page.getByRole("link", { name: "Shopping list" }).click();
  await expect(dee.page.getByRole("heading", { level: 1, name: `${cal.name}'s shopping list` })).toBeVisible();
  await expect(dee.page.getByRole("checkbox", { name: new RegExp(calFood.name) })).toBeDisabled();

  // Cal stops sharing; Dee no longer gets the choice.
  await cal.page.goto("/plan");
  await cal.page.getByText("Share your plan").click();
  await cal.page.getByRole("button", { name: `Remove ${dee.name}'s access` }).click();
  await expect(cal.page.getByText("You haven't shared your plan with anyone.")).toBeVisible();
  await expect(cal.page.getByRole("heading", { name: "Who can see your plan" })).toBeFocused();

  await dee.page.goto("/plan");
  await expect(dee.page.getByRole("heading", { level: 1, name: "Plan" })).toBeVisible();
  await expect(dee.page.getByLabel("Whose plan")).toHaveCount(0);
  await dee.page.goto(`/plan?of=${cal.id}`);
  await expect(dee.page.getByText("This plan isn't shared with you (any more).")).toBeVisible();

  // Leaving a plan from the other side works too.
  await api(cal.page.request, "PUT", "/api/plan-shares", { email: dee.email, can_edit: true });
  await dee.page.goto("/plan");
  await dee.page.getByText("Share your plan").click();
  dee.page.once("dialog", (d) => d.accept());
  await dee.page.getByRole("button", { name: `Stop seeing ${cal.name}'s plan` }).click();
  await expect(dee.page.getByText("Nobody has shared their plan with you.")).toBeVisible();
  await expect(dee.page.getByLabel("Whose plan")).toHaveCount(0);

  await cal.close();
  await dee.close();
});

test("admin manages who can see a user's plan", async ({ page, browser }) => {
  test.setTimeout(60_000);
  const eve = await person(browser, page.request, "Eve");
  const fay = await person(browser, page.request, "Fay");
  await page.goto("/settings/users");
  const card = page.locator("li.user-row").filter({ hasText: eve.email });
  await card.getByText("Plan access").click();
  const shareForm = card.getByRole("form", { name: `Share ${eve.name}'s plan` });
  await expect(card.getByText(`Nobody else can see ${eve.name}'s plan.`)).toBeVisible();
  await shareForm.getByLabel("Share with (email)").fill("nobody-here@example.com");
  await shareForm.getByRole("button", { name: "Share" }).click();
  await expect(shareForm.getByLabel("Share with (email)")).toHaveAccessibleDescription(/No active account with that email/);

  await shareForm.getByLabel("Share with (email)").fill(fay.email);
  await shareForm.getByLabel("View only").check();
  await shareForm.getByRole("button", { name: "Share" }).click();
  await expect(shareForm.getByText(`${fay.name} can now see ${eve.name}'s plan.`)).toBeVisible();
  const shares = await api(fay.page.request, "GET", "/api/plan-shares");
  expect(shares.shared_with_me).toMatchObject([{ user_id: eve.id, can_edit: false }]);

  await card.getByRole("button", { name: `Allow editing for ${fay.name}` }).click();
  await expect(card.getByRole("button", { name: `Make view only for ${fay.name}` })).toBeVisible();
  expect((await api(fay.page.request, "GET", "/api/plan-shares")).shared_with_me[0].can_edit).toBe(true);

  await card.getByRole("button", { name: `Remove ${fay.name}'s access` }).click();
  await expect(card.getByText(`Nobody else can see ${eve.name}'s plan.`)).toBeVisible();
  expect((await api(fay.page.request, "GET", "/api/plan-shares")).shared_with_me).toEqual([]);

  await eve.close();
  await fay.close();
});
