import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { fmtNum, mealLabel, parseNum, unitText } from "../lib";
import { MEALS, type FoodSummary, type Meal, type SavedMeal, type WeighedState } from "../types";
import { QuantityFields, unitChoices } from "./AmountFields";
import { ErrorBox, Field, Loading } from "./common";
import { FoodPicker } from "./FoodPicker";

type DraftItem = {
  key: string;
  food_id: number | null;
  recipe_id: number | null;
  label: string;
  quantity: string;
  unit: string;
  weighed_state: WeighedState;
  yield_id: number | null;
};

let draftSeq = 0;
const draftKey = () => `d${++draftSeq}`;

function ItemEditor({ item, onChange, onRemove }: { item: DraftItem; onChange: (i: DraftItem) => void; onRemove: () => void }) {
  const food = useQuery({ queryKey: ["food", item.food_id], queryFn: () => api.food(item.food_id!), enabled: !!item.food_id });
  const recipe = useQuery({ queryKey: ["recipe", item.recipe_id], queryFn: () => api.recipe(item.recipe_id!), enabled: !!item.recipe_id });
  return (
    <li className="saved-item-edit">
      <div className="row between">
        <strong className="grow">{item.label}</strong>
        <button type="button" className="btn-link danger small" onClick={onRemove} aria-label={`Remove ${item.label}`}>
          Remove
        </button>
      </div>
      {item.weighed_state === "cooked" && <span className="muted small">Weighed after cooking</span>}
      <QuantityFields
        quantity={item.quantity}
        unit={item.unit}
        options={unitChoices(food.data, recipe.data, item.weighed_state, item.unit)}
        onQuantity={(quantity) => onChange({ ...item, quantity })}
        onUnit={(unit) => onChange({ ...item, unit })}
      />
    </li>
  );
}

function SavedMealEditor({ meal, onDone }: { meal: SavedMeal; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(meal.name);
  const [defaultMeal, setDefaultMeal] = useState<Meal>(meal.default_meal);
  const [items, setItems] = useState<DraftItem[]>(() =>
    meal.items.map((it) => ({ ...it, key: draftKey(), quantity: String(it.quantity) })),
  );
  const [adding, setAdding] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      api.updateSavedMeal(meal.id, {
        name: name.trim(),
        default_meal: defaultMeal,
        items: items.map((it) => ({
          food_id: it.food_id,
          recipe_id: it.recipe_id,
          quantity: parseNum(it.quantity) ?? 0,
          unit: it.unit,
          weighed_state: it.weighed_state,
          yield_id: it.yield_id,
        })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saved-meals"] });
      onDone();
    },
  });
  const valid = name.trim() && items.length > 0 && items.every((it) => (parseNum(it.quantity) ?? 0) > 0);

  function add(f: FoodSummary) {
    const serving = f.basis === "serving";
    setItems([
      ...items,
      {
        key: draftKey(),
        food_id: f.id,
        recipe_id: null,
        label: f.name + (f.brand ? ` (${f.brand})` : ""),
        quantity: serving ? "1" : "100",
        unit: serving ? "serving" : "g",
        weighed_state: "as_is",
        yield_id: null,
      },
    ]);
    setAdding(false);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (valid) save.mutate();
  }

  return (
    <form className="stack" onSubmit={submit} aria-label={`Edit ${meal.name}`}>
      <div className="grid-2">
        <Field label="Name">
          <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Usual meal">
          <select value={defaultMeal} onChange={(e) => setDefaultMeal(e.target.value as Meal)}>
            {MEALS.map((m) => (
              <option key={m} value={m}>
                {mealLabel(m)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ul className="plain-list stack-sm">
        {items.map((it) => (
          <ItemEditor
            key={it.key}
            item={it}
            onChange={(n) => setItems(items.map((x) => (x.key === it.key ? n : x)))}
            onRemove={() => setItems(items.filter((x) => x.key !== it.key))}
          />
        ))}
      </ul>
      {items.length === 0 && <p className="muted small">A saved meal needs at least one item.</p>}
      {adding ? (
        <div className="stack-sm">
          <FoodPicker onPick={add} placeholder="Search for a food to add…" />
          <div>
            <button type="button" className="btn-link" onClick={() => setAdding(false)}>
              Cancel adding
            </button>
          </div>
        </div>
      ) : (
        <div>
          <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}>
            + Add item
          </button>
        </div>
      )}
      <ErrorBox error={save.error} />
      <div className="row wrap">
        <button type="submit" className="btn btn-primary" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function SavedMealCard({ meal, logMeal, when }: { meal: SavedMeal; logMeal: Meal | ""; when: string }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [logged, setLogged] = useState<string | null>(null);
  const log = useMutation({
    mutationFn: () => api.logSavedMeal(meal.id, { meal: logMeal || null, consumed_at: new Date(when).toISOString() }),
    onMutate: () => setLogged(null),
    onSuccess: (entries) => {
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      setLogged(`Logged ${entries.length} item${entries.length === 1 ? "" : "s"} to ${logMeal || meal.default_meal}.`);
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteSavedMeal(meal.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-meals"] }),
  });

  return (
    <li className="card stack-sm">
      <div className="row between wrap">
        <div className="row wrap">
          <strong>{meal.name}</strong>
          <span className="chip">{meal.default_meal}</span>
        </div>
        {!editing && (
          <div className="row wrap">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => log.mutate()} disabled={log.isPending}>
              {log.isPending ? "Logging…" : "Log"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              type="button"
              className="btn btn-sm danger"
              disabled={del.isPending}
              onClick={() => {
                if (confirm(`Delete the saved meal "${meal.name}"? Logged entries stay.`)) del.mutate();
              }}
            >
              Delete
            </button>
          </div>
        )}
      </div>
      {editing ? (
        <SavedMealEditor meal={meal} onDone={() => setEditing(false)} />
      ) : (
        <ul className="plain-list small saved-items">
          {meal.items.map((it) => (
            <li key={it.id}>
              {it.label} <span className="muted">— {fmtNum(it.quantity)} {unitText(it.unit)}</span>
            </li>
          ))}
        </ul>
      )}
      {logged && (
        <p className="ok-text small" role="status">
          ✓ {logged} <Link to="/">View day</Link>
        </p>
      )}
      <ErrorBox error={log.error || del.error} />
    </li>
  );
}

/** Saved meals with one-click logging. ``logMeal`` "" means each meal's own default. */
export function SavedMeals({ logMeal, when }: { logMeal: Meal | ""; when: string }) {
  const meals = useQuery({ queryKey: ["saved-meals"], queryFn: api.savedMeals });
  if (meals.isLoading) return <Loading />;
  return (
    <div className="stack">
      <ErrorBox error={meals.error} />
      {meals.data?.length === 0 && (
        <p className="muted">
          No saved meals yet. On the <Link to="/">Today</Link> page, use “Save as meal…” on a meal you eat often to save it here.
        </p>
      )}
      <ul className="plain-list cards">
        {meals.data?.map((m) => (
          <SavedMealCard key={m.id} meal={m} logMeal={logMeal} when={when} />
        ))}
      </ul>
    </div>
  );
}
