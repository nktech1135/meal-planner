import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { api } from "./helpers";

/*
 * Sharing a whole profile: the owner grants access on the Account page, the other person switches to it
 * from the Me menu and works in it (with a banner saying whose it is), switches back, and is sent back
 * to their own when access is withdrawn. Each person has their own browser context.
 */

const tag = () => Math.random().toString(36).slice(2, 7);

type Person = { id: number; name: string; email: string; page: Page; req: APIRequestContext; close: () => Promise<void> };

async function person(browser: Browser, admin: APIRequestContext, first: string): Promise<Person> {
  const t = tag();
  const name = `${first} ${t}`;
  const email = `${first.toLowerCase()}-${t}@example.com`;
  const password = `${first} password ${t}`;
  const { user } = await api(admin, "POST", "/api/admin/users", { email, display_name: name, password });
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  await api(ctx.request, "POST", "/api/auth/login", { email, password });
  await api(ctx.request, "PUT", "/api/profile", { sex: "female", birth_date: "1990-01-01", height_cm: 165, weight_kg: 60, timezone: "UTC" });
  return { id: user.id, name, email, page: await ctx.newPage(), req: ctx.request, close: () => ctx.close() };
}

async function audit(page: Page, label: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]).analyze();
  const report = violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`).join("\n");
  expect.soft(violations, `axe violations on ${label}:\n${report}`).toEqual([]);
}

test("share a profile, switch to it, work in it and switch back", async ({ page, browser }) => {
  const ann = await person(browser, page.request, "Ann");
  const ben = await person(browser, page.request, "Ben");
  const muesli = await api(ann.req, "POST", "/api/foods", { name: `Ann's muesli ${tag()}`, nutrients: { energy_kcal: 380 }, citation: "e2e test" });
  await api(ann.req, "POST", "/api/log", { food_id: muesli.id, quantity: 60, unit: "g", meal: "breakfast" });

  // Ann shares her profile from her Account page.
  await ann.page.goto("/account");
  const section = ann.page.getByRole("region", { name: "Share your profile" });
  await section.getByLabel("Share with (email)").fill(ben.email);
  await section.getByRole("button", { name: "Share" }).click();
  await expect(section.getByText(`${ben.name} can now use and edit your profile.`)).toBeVisible();

  // Ben switches to it from the Me menu.
  await ben.page.goto("/");
  await ben.page.getByRole("button", { name: /^B?\s*Me/ }).click();
  const switcher = ben.page.getByRole("group", { name: "Switch profile" });
  await expect(switcher.getByRole("button", { name: "Your own" })).toHaveAttribute("aria-current", "true");
  await switcher.getByRole("button", { name: ann.name }).click();

  const banner = ben.page.getByRole("region", { name: "Profile in use" });
  await expect(banner).toContainText(`You're using ${ann.name}'s profile · you can change anything in it.`);
  await expect(ben.page).toHaveTitle(`Today – ${ann.name}'s profile – Mealplan`);
  await expect(ben.page.getByText(muesli.name)).toBeVisible(); // Ann's log
  await audit(ben.page, "Today, using someone else's profile");

  // What he changes is hers, and what he logs says he did it.
  await ben.page.goto("/profile");
  await ben.page.getByLabel("Weight (kg)").fill("58");
  await ben.page.getByRole("button", { name: "Save profile" }).click();
  await expect(ben.page.getByText("Saved.")).toBeVisible();
  expect((await api(ann.req, "GET", "/api/profile")).weight_kg).toBe(58);
  expect((await api(ben.req, "GET", "/api/profile")).weight_kg).toBe(60);
  await ben.page.evaluate(
    async ([id, food]) => {
      await fetch("/api/log", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Mealplan-Profile": String(id) },
        body: JSON.stringify({ food_id: food, quantity: 30, unit: "g", meal: "snack" }),
      });
    },
    [ann.id, muesli.id],
  );
  await ann.page.goto("/");
  await expect(ann.page.getByText(`Added by ${ben.name}`)).toBeVisible();

  // The menu shows whose profile is in use; his account stays his own.
  const menuButton = ben.page.getByRole("button", { name: new RegExp(`${ann.name}.*using their profile`) });
  await menuButton.click();
  await expect(ben.page.getByRole("group", { name: "Switch profile" }).getByRole("button", { name: ann.name })).toHaveAttribute("aria-current", "true");
  await audit(ben.page, "Me menu open, using someone else's profile");
  await ben.page.getByRole("link", { name: "Your account" }).click();
  await expect(ben.page.getByText("This is your own account.")).toBeVisible();
  await expect(ben.page.getByLabel("Email", { exact: true })).toHaveValue(ben.email);

  // Back to his own.
  await banner.getByRole("button", { name: "Switch back to your own profile" }).click();
  await expect(ben.page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(banner).toHaveCount(0);
  await expect(ben.page).toHaveTitle("Today – Mealplan");
  await expect(ben.page.getByText(muesli.name)).toHaveCount(0);

  // Withdrawn while he's using it: the next request sends him back to his own, with a notice.
  await ben.page.getByRole("button", { name: /Me/ }).click();
  await ben.page.getByRole("group", { name: "Switch profile" }).getByRole("button", { name: ann.name }).click();
  await expect(banner).toBeVisible();
  await api(ann.req, "DELETE", `/api/profile-access/${ben.id}`);
  await ben.page.getByRole("link", { name: "Trends" }).click();
  await expect(ben.page.getByText(`${ann.name}'s profile isn't shared with you any more, so you're back on your own.`)).toBeVisible();
  await expect(banner).toHaveCount(0);

  await ann.close();
  await ben.close();
});

test("view-only access, and admins granting it", async ({ page, browser }) => {
  const cat = await person(browser, page.request, "Cat");
  const dan = await person(browser, page.request, "Dan");

  // The admin gives Dan view-only access to Cat's profile from Settings → Users.
  await page.goto("/settings/users");
  const row = page.locator("li, tr, .user-row").filter({ hasText: cat.email }).first();
  await row.getByText("Profile access").click();
  const form = row.getByRole("form", { name: `Share ${cat.name}'s profile` });
  await form.getByLabel("Share with (email)").fill(dan.email);
  await form.getByLabel("View only").check();
  await form.getByRole("button", { name: "Share" }).click();
  await expect(form.getByText(`${dan.name} can now use ${cat.name}'s profile.`)).toBeVisible();

  await dan.page.goto("/");
  await dan.page.getByRole("button", { name: /Me/ }).click();
  await dan.page.getByRole("group", { name: "Switch profile" }).getByRole("button", { name: `${cat.name} · view only` }).click();
  await expect(dan.page.getByRole("region", { name: "Profile in use" })).toContainText(`You're using ${cat.name}'s profile · view only.`);

  // Saving is refused, with the reason.
  await dan.page.goto("/profile");
  await dan.page.getByLabel("Weight (kg)").fill("70");
  await dan.page.getByRole("button", { name: "Save profile" }).click();
  await expect(dan.page.getByText(`${cat.name} shared their profile with you to view only`)).toBeVisible();
  expect((await api(cat.req, "GET", "/api/profile")).weight_kg).toBe(60);

  await cat.close();
  await dan.close();
});
