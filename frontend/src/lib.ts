import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { NutrientDef } from "./types";

export function useNutrients() {
  const q = useQuery({ queryKey: ["nutrients"], queryFn: api.nutrients, staleTime: Infinity });
  const list = q.data ?? [];
  const byCode: Record<string, NutrientDef> = Object.fromEntries(list.map((n) => [n.code, n]));
  return { list, byCode, isLoading: q.isLoading };
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
};

export const parseNum = (s: string): number | null => {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};
