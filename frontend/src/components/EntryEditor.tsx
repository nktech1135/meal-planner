import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { mealLabel, parseNum, toLocalInput } from "../lib";
import { MEALS, type LogEntry, type LogUpdate, type Meal, type WeighedState } from "../types";
import { QuantityFields, unitChoices, WeighedFields } from "./AmountFields";
import { ErrorBox, Field, Loading } from "./common";

/** Inline editor for a log entry; sends only the fields that changed. */
export function EntryEditor({ entry, onDone }: { entry: LogEntry; onDone: () => void }) {
  const qc = useQueryClient();
  const orphan = entry.food_id === null && entry.recipe_id === null;
  const food = useQuery({ queryKey: ["food", entry.food_id], queryFn: () => api.food(entry.food_id!), enabled: !!entry.food_id });
  const recipe = useQuery({ queryKey: ["recipe", entry.recipe_id], queryFn: () => api.recipe(entry.recipe_id!), enabled: !!entry.recipe_id });
  const originalWhen = toLocalInput(entry.consumed_at);
  const [quantity, setQuantity] = useState(String(entry.quantity));
  const [unit, setUnit] = useState(entry.unit);
  const [weighed, setWeighed] = useState<WeighedState>(entry.weighed_state);
  const [yieldId, setYieldId] = useState<number | null>(entry.yield_id);
  const [meal, setMeal] = useState<Meal>(entry.meal);
  const [when, setWhen] = useState(originalWhen);
  const [note, setNote] = useState(entry.note);

  const changes: LogUpdate = {};
  if (!orphan) {
    const q = parseNum(quantity);
    if (q !== null && q !== entry.quantity) changes.quantity = q;
    if (unit !== entry.unit) changes.unit = unit;
    if (weighed !== entry.weighed_state) changes.weighed_state = weighed;
    const y = weighed === "cooked" ? yieldId : null;
    if (y !== entry.yield_id) changes.yield_id = y;
  }
  if (meal !== entry.meal) changes.meal = meal;
  if (when && when !== originalWhen) changes.consumed_at = new Date(when).toISOString();
  if (note !== entry.note) changes.note = note;
  const qty = parseNum(quantity);
  const invalid = !orphan && (!qty || qty <= 0 || (weighed === "cooked" && !yieldId));

  const save = useMutation({
    mutationFn: () => api.updateLog(entry.id, changes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (invalid) return;
    if (Object.keys(changes).length === 0) onDone();
    else save.mutate();
  }

  const loadingItem = (food.isLoading && !!entry.food_id) || (recipe.isLoading && !!entry.recipe_id);

  return (
    <form className="entry-editor stack" onSubmit={submit} aria-label={`Edit ${entry.label}`}>
      {orphan && (
        <p className="alert alert-info small">The food for this entry was deleted, so only the time, meal and note can change.</p>
      )}
      {!orphan && loadingItem && <Loading />}
      <ErrorBox error={food.error || recipe.error} />
      {!orphan && !loadingItem && (
        <>
          {food.data && (
            <WeighedFields
              food={food.data}
              weighed={weighed}
              yieldId={yieldId}
              onWeighed={(w) => {
                setWeighed(w);
                if (w === "cooked") setUnit("g");
                else setYieldId(null);
              }}
              onYield={setYieldId}
            />
          )}
          <QuantityFields
            quantity={quantity}
            unit={unit}
            options={unitChoices(food.data, recipe.data, weighed, unit)}
            onQuantity={setQuantity}
            onUnit={setUnit}
          />
        </>
      )}
      <div className="grid-2">
        <Field label="Meal">
          <select value={meal} onChange={(e) => setMeal(e.target.value as Meal)}>
            {MEALS.map((m) => (
              <option key={m} value={m}>
                {mealLabel(m)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="When">
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
        </Field>
      </div>
      <Field label="Note">
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <ErrorBox error={save.error} />
      <div className="row wrap">
        <button type="submit" className="btn btn-primary btn-sm" disabled={invalid || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
