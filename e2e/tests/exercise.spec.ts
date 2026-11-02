import { expect, test } from "@playwright/test";
import { api, today } from "./helpers";

test.beforeEach(async ({ page }) => {
  await api(page.request, "PUT", "/api/profile", {
    sex: "female", birth_date: "1990-01-01", height_cm: 168, weight_kg: 60, timezone: "UTC",
  });
  for (const x of await api(page.request, "GET", "/api/exercise")) await api(page.request, "DELETE", `/api/exercise/${x.id}`);
});

test("logging a workout raises the day's energy target", async ({ page }) => {
  const before = await api(page.request, "GET", "/api/summary/day");
  const target = (s: any) => s.evaluation.find((r: any) => r.code === "energy_kcal").target;

  await page.goto("/exercise");
  await page.getByLabel("Find an activity").fill("jogging general");
  await page.getByLabel("Activity", { exact: true }).selectOption({ label: "Jogging, general, self-selected pace (7.5 MET)" });
  await expect(page.getByLabel("Name")).toHaveValue("Jogging, general, self-selected pace");
  await page.getByLabel("Duration (min)").fill("40");
  await page.getByRole("button", { name: "Log workout" }).click();

  // (7.5 - 1) MET × weight × 40/60 h, with the latest weigh-in (other specs record some) or the profile weight
  const recent = page.getByRole("region", { name: "Last 30 days" });
  await expect(recent.getByText(/kcal · Compendium METs/)).toBeVisible();
  const [logged] = await api(page.request, "GET", "/api/exercise");
  const kcal = Math.round(6.5 * logged.weight_kg * (40 / 60));
  expect(Math.round(logged.kcal)).toBe(kcal);
  await expect(recent.getByText(`+${kcal} kcal · Compendium METs`)).toBeVisible();
  const after = await api(page.request, "GET", "/api/summary/day");
  expect(target(after)).toBe(target(before) + kcal);

  await page.goto("/");
  await expect(page.getByText(`${kcal} kcal above resting is included in this day's energy target.`)).toBeVisible();
  await expect(page.getByText(new RegExp(`Includes ${kcal} kcal of logged exercise`)).first()).toBeVisible();

  await page.goto("/exercise");
  await recent.getByRole("button", { name: /^Delete Jogging/ }).click();
  await expect(recent.getByText("No workouts logged in this period.")).toBeVisible();
});

test("importing a GPX file estimates energy from the activity type", async ({ page }) => {
  const start = new Date(`${today()}T06:00:00Z`);
  const points = Array.from({ length: 31 }, (_, i) =>
    `<trkpt lat="${51.5 + i * 0.001}" lon="-0.12"><time>${new Date(start.getTime() + i * 60_000).toISOString()}</time></trkpt>`).join("");
  const gpx = `<?xml version="1.0"?><gpx version="1.1" creator="e2e" xmlns="http://www.topografix.com/GPX/1/1">` +
    `<trk><type>hiking</type><trkseg>${points}</trkseg></trk></gpx>`;

  await page.goto("/exercise");
  const files = page.getByLabel("Files", { exact: true });
  await files.setInputFiles({ name: "hike.gpx", mimeType: "application/gpx+xml", buffer: Buffer.from(gpx) });
  await page.getByRole("button", { name: "Import 1 file" }).click();
  await expect(page.getByText("Imported 1 workout.")).toBeVisible();
  // (5.3 - 1) MET × weight × 0.5 h
  const [hike] = await api(page.request, "GET", "/api/exercise");
  await expect(page.getByText(`+${Math.round(4.3 * hike.weight_kg * 0.5)} kcal · Compendium METs`)).toBeVisible();
  await expect(page.getByRole("region", { name: "Last 30 days" }).getByText(/Hiking or walking at a normal pace/).first()).toBeVisible();

  await files.setInputFiles({ name: "hike.gpx", mimeType: "application/gpx+xml", buffer: Buffer.from(gpx) });
  await page.getByRole("button", { name: "Import 1 file" }).click();
  await expect(page.getByText("Imported 0 workouts, skipped 1 already imported.")).toBeVisible();
});
