import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { AppInfo, Food, Meal, NutrientDef, Recipe, UnitSystem, WeighedState } from "./types";

export function useNutrients() {
  const q = useQuery({ queryKey: ["nutrients"], queryFn: api.nutrients, staleTime: Infinity });
  const list = q.data ?? [];
  const byCode: Record<string, NutrientDef> = Object.fromEntries(list.map((n) => [n.code, n]));
  return { list, byCode, isLoading: q.isLoading };
}

/** Public server facts (sign-ups open, advisor configured, USDA demo key). Works signed out. */
export function useAppInfo(): AppInfo | undefined {
  return useQuery({ queryKey: ["app-info"], queryFn: api.appInfo, staleTime: 5 * 60_000 }).data;
}

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs === 0) return "0";
  if (abs >= 100) return Math.round(v).toLocaleString();
  return Number(v.toPrecision(digits)).toLocaleString();
}

export function fmtAmount(v: number | null | undefined, unit?: string): string {
  const n = fmtNum(v);
  return unit && n !== "—" ? `${n} ${unit}` : n;
}

export function nutrientName(byCode: Record<string, NutrientDef>, code: string): string {
  return byCode[code]?.name ?? code;
}

/** Today's date (YYYY-MM-DD) in the browser's timezone. */
export function todayISO(): string {
  const d = new Date();
  return localDateISO(d);
}

export function localDateISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Value for <input type="datetime-local"> representing now. */
export function nowLocalInput(): string {
  const d = new Date();
  d.setSeconds(0, 0);
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
}

/** Convert an ISO timestamp to a <input type="datetime-local"> value in the browser's zone. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  d.setSeconds(0, 0);
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
}

/** Shift a YYYY-MM-DD date by whole days. */
export function addDays(day: string, days: number): string {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + days);
  return localDateISO(d);
}

export function fmtDay(day: string): string {
  if (day === todayISO()) return "today";
  if (day === addDays(todayISO(), -1)) return "yesterday";
  if (day === addDays(todayISO(), 1)) return "tomorrow";
  return new Date(`${day}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

/** A sensible meal for the current time of day. */
export function defaultMeal(): Meal {
  const h = new Date().getHours();
  if (h < 10) return "breakfast";
  if (h < 15) return "lunch";
  if (h < 21) return "dinner";
  return "snack";
}

export const mealLabel = (m: string) => m[0].toUpperCase() + m.slice(1);

/** Human text for a logged unit ("portion:12" -> the portion's label when known). */
export function unitText(unit: string, food?: Food | null): string {
  if (unit.startsWith("portion:")) {
    const p = food?.portions.find((x) => `portion:${x.id}` === unit);
    return p ? p.label : "portion";
  }
  if (unit === "serving") return "serving";
  return unit;
}

export type UnitOption = { value: string; label: string };

/** Units a food can be logged in (g / serving / unit / portion:<id>). */
export function unitOptions(f: Food, weighed: WeighedState): UnitOption[] {
  if (weighed === "cooked") return [{ value: "g", label: "grams (cooked weight)" }];
  if (f.basis === "100g") {
    const opts = [{ value: "g", label: "grams" }];
    if (f.serving_size_g) opts.push({ value: "serving", label: `servings (${fmtNum(f.serving_size_g)} g)` });
    for (const p of f.portions) opts.push({ value: `portion:${p.id}`, label: `${p.label} (${fmtNum(p.gram_weight)} g)` });
    return opts;
  }
  const opts = [
    { value: "serving", label: `servings (${fmtNum(f.serving_quantity ?? 1)} ${f.serving_unit ?? "unit"})` },
    { value: "unit", label: f.serving_unit ? `individual ${f.serving_unit}` : "individual units" },
  ];
  if (f.serving_size_g) opts.push({ value: "g", label: "grams" });
  return opts;
}

export function recipeUnitOptions(r: Pick<Recipe, "servings" | "cooked_weight_g">): UnitOption[] {
  const opts = [{ value: "serving", label: `servings (of ${fmtNum(r.servings)})` }];
  if (r.cooked_weight_g) opts.push({ value: "g", label: "grams of finished dish" });
  return opts;
}

/** Raw (uncooked, per-100 g) foods can be weighed after cooking via a cooking yield. */
export const canWeighCooked = (f: Food) => f.basis === "100g" && f.state !== "cooked";

/** Per-viewer preference in localStorage; storage may be unavailable (private mode etc.). */
export function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore: the preference just won't persist
  }
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function basisLabel(f: { basis: string; serving_quantity: number | null; serving_unit: string | null }): string {
  if (f.basis === "100g") return "per 100 g";
  const q = f.serving_quantity ? `${fmtNum(f.serving_quantity)} ` : "";
  return `per serving (${q}${f.serving_unit ?? "serving"})`;
}

export const SOURCE_NAMES: Record<string, string> = {
  manual: "Manual entry",
  usda_fdc: "USDA FoodData Central",
  nih_dsld: "NIH Dietary Supplement Label Database",
  nutritionix: "Nutritionix",
  edamam: "Edamam",
  open_food_facts: "Open Food Facts",
  afcd: "Australian Food Composition Database (FSANZ)",
  cofid: "UK Composition of Foods Integrated Dataset (CoFID)",
  bls: "German Nutrient Database (BLS, Max Rubner-Institut)",
  cnf: "Canadian Nutrient File (Health Canada)",
  ciqual: "French Food Composition Table (Ciqual, ANSES)",
  matvaretabellen: "Norwegian Food Composition Table (Mattilsynet)",
  dk_fcdb: "Danish Food Composition Database (DTU Food Institute)",
  swiss: "Swiss Food Composition Database (FSVO)",
  se_livsmedel: "Swedish Food Composition Database (Livsmedelsverket)",
  fineli: "Finnish Food Composition Database (Fineli, THL)",
};

export const parseNum = (s: string): number | null => {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** The signed-in user's unit preference (metric until the profile says otherwise). */
export function useUnitSystem(): UnitSystem {
  const q = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  return q.data?.unit_system ?? "metric";
}

// --- units: the API is always metric; imperial is display/entry only -------------

export const LB_PER_KG = 2.20462;
export const CM_PER_IN = 2.54;
const G_PER_OZ = 28.3495;

export const weightUnit = (u: UnitSystem) => (u === "imperial" ? "lb" : "kg");
export const lengthUnit = (u: UnitSystem) => (u === "imperial" ? "in" : "cm");

/** kg -> the user's unit. */
export const toWeight = (kg: number, u: UnitSystem) => (u === "imperial" ? kg * LB_PER_KG : kg);
/** The user's unit -> kg. */
export const fromWeight = (v: number, u: UnitSystem) => (u === "imperial" ? v / LB_PER_KG : v);
export const toLength = (cm: number, u: UnitSystem) => (u === "imperial" ? cm / CM_PER_IN : cm);
export const fromLength = (v: number, u: UnitSystem) => (u === "imperial" ? v * CM_PER_IN : v);

/** One decimal, trailing zero dropped: 72.0 -> "72", 158.73 -> "158.7". */
export const fmt1 = (v: number) => (Math.round(v * 10) / 10).toLocaleString();

export function fmtWeight(kg: number | null | undefined, u: UnitSystem): string {
  if (kg === null || kg === undefined) return "—";
  return `${fmt1(toWeight(kg, u))} ${weightUnit(u)}`;
}

/** Shopping amounts: "350 g", "1.2 kg"; imperial users also get "(12.3 oz)" / "(2.6 lb)". */
export function fmtGrams(g: number, u: UnitSystem): string {
  const metric = g >= 1000 ? `${fmt1(g / 1000)} kg` : `${Math.round(g).toLocaleString()} g`;
  if (u !== "imperial") return metric;
  const oz = g / G_PER_OZ;
  return `${metric} (${oz >= 16 ? `${fmt1(oz / 16)} lb` : `${fmt1(oz)} oz`})`;
}

/** Monday of the week containing ``day`` (YYYY-MM-DD). */
export function mondayOf(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  return addDays(day, -((d.getDay() + 6) % 7));
}

export function fmtShortDate(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
}

export function weekdayShort(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString([], { weekday: "short" });
}

/** Tracks a CSS media query (e.g. phone width). */
export function useMedia(query: string): boolean {
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}
