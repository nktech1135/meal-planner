import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export const today = () => new Date().toISOString().slice(0, 10);
export const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

export async function api<T = any>(req: APIRequestContext, method: string, url: string, data?: unknown): Promise<T> {
  const resp = await req.fetch(url, { method, data });
  expect(resp.ok(), `${method} ${url}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  return resp.status() === 204 ? (undefined as T) : resp.json();
}

/** A uniquely named manual food, so tests don't depend on each other. */
export async function makeFood(page: Page, name: string, extra: Record<string, unknown> = {}) {
  return api(page.request, "POST", "/api/foods", {
    name: `${name} ${Math.random().toString(36).slice(2, 7)}`,
    nutrients: { energy_kcal: 100, protein_g: 5 },
    citation: "e2e test",
    ...extra,
  });
}
