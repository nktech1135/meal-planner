import { useId } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { canWeighCooked, fmtNum, recipeUnitOptions, unitOptions, type UnitOption } from "../lib";
import type { Food, Recipe, WeighedState } from "../types";
import { Field } from "./common";
import { VisuallyHidden } from "./a11y";

/** Keep a value that isn't (or is no longer) offered visible in the select instead of silently switching. */
export function withCurrent(opts: UnitOption[], unit: string): UnitOption[] {
  return opts.some((o) => o.value === unit) || !unit ? opts : [...opts, { value: unit, label: unit.startsWith("portion:") ? "portion (removed)" : unit }];
}

export function unitChoices(food: Food | null | undefined, recipe: Recipe | null | undefined, weighed: WeighedState, unit: string): UnitOption[] {
  if (food) return withCurrent(unitOptions(food, weighed), unit);
  if (recipe) return withCurrent(recipeUnitOptions(recipe), unit);
  return withCurrent([], unit);
}

/** "How did you weigh it?" for raw foods, with the cooking-yield picker. */
export function WeighedFields({
  food,
  weighed,
  yieldId,
  onWeighed,
  onYield,
}: {
  food: Food;
  weighed: WeighedState;
  yieldId: number | null;
  onWeighed: (w: WeighedState) => void;
  onYield: (id: number | null) => void;
}) {
  const name = useId();
  const yields = useQuery({
    queryKey: ["yields", food.id],
    queryFn: () => api.yields(food.id),
    enabled: weighed === "cooked",
  });
  if (!canWeighCooked(food)) return null;
  return (
    <fieldset className="fieldset">
      <legend>How did you weigh it?</legend>
      <label className="radio">
        <input type="radio" name={name} checked={weighed === "as_is"} onChange={() => onWeighed("as_is")} />
        As described ({food.state ?? "as sold"})
      </label>
      <label className="radio">
        <input type="radio" name={name} checked={weighed === "cooked"} onChange={() => onWeighed("cooked")} />
        I weighed it after cooking
      </label>
      {weighed === "cooked" && (
        <Field label="Cooking yield" hint="Converts cooked weight back to raw weight for the nutrient calculation.">
          {yields.data && yields.data.length === 0 ? (
            <p className="alert alert-warn">
              No cooking yields for this food yet. <Link to={`/foods/${food.id}`}>Add one on the food page</Link> (weigh it raw and cooked once).
            </p>
          ) : (
            <select value={yieldId ?? ""} onChange={(e) => onYield(e.target.value ? Number(e.target.value) : null)} required>
              <option value="">Choose a yield…</option>
              {yields.data?.map((y) => (
                <option key={y.id} value={y.id}>
                  {y.method} — ×{fmtNum(y.yield_factor, 3)} ({y.basis}, {y.trust_level})
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
    </fieldset>
  );
}

/** Amount + unit inputs. */
export function QuantityFields({
  quantity,
  unit,
  options,
  onQuantity,
  onUnit,
  context,
}: {
  quantity: string;
  unit: string;
  options: UnitOption[];
  onQuantity: (v: string) => void;
  onUnit: (v: string) => void;
  /** Item name, for screen readers when several of these are on one form. */
  context?: string;
}) {
  const of = context ? <VisuallyHidden> of {context}</VisuallyHidden> : null;
  const forItem = context ? <VisuallyHidden> for {context}</VisuallyHidden> : null;
  return (
    <div className="grid-2">
      <Field label={<>Amount{of}</>}>
        <input type="number" inputMode="decimal" min="0" step="any" value={quantity} onChange={(e) => onQuantity(e.target.value)} required />
      </Field>
      <Field label={<>Unit{forItem}</>}>
        <select value={unit} onChange={(e) => onUnit(e.target.value)}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}
