import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ComponentList, ErrorBox, Field, MacroLine, Notes, NutrientTable } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { TrustBadge } from "../components/TrustBadge";
import { basisLabel, fmtNum, nowLocalInput, parseNum } from "../lib";
import { MEALS, type CalculateInput, type Food, type FoodSummary, type Meal, type WeighedState } from "../types";

function defaultMeal(): Meal {
  const h = new Date().getHours();
  if (h < 10) return "breakfast";
  if (h < 15) return "lunch";
  if (h < 21) return "dinner";
  return "snack";
}

function unitOptions(f: Food, weighed: WeighedState): { value: string; label: string }[] {
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

function useDebouncedValue<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function AddEntryPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"food" | "recipe">("food");
  const [picked, setPicked] = useState<FoodSummary | null>(null);
  const [recipeId, setRecipeId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("100");
  const [unit, setUnit] = useState("g");
  const [weighed, setWeighed] = useState<WeighedState>("as_is");
  const [yieldId, setYieldId] = useState<number | null>(null);
  const [meal, setMeal] = useState<Meal>(defaultMeal());
  const [when, setWhen] = useState(nowLocalInput());
  const [note, setNote] = useState("");

  const food = useQuery({ queryKey: ["food", picked?.id], queryFn: () => api.food(picked!.id), enabled: !!picked });
  const recipes = useQuery({ queryKey: ["recipes"], queryFn: api.recipes, enabled: mode === "recipe" });
  const canCook = !!food.data && food.data.basis === "100g" && food.data.state !== "cooked";
  const yields = useQuery({
    queryKey: ["yields", picked?.id],
    queryFn: () => api.yields(picked!.id),
    enabled: !!picked && canCook && weighed === "cooked",
  });
  const recipe = recipes.data?.find((r) => r.id === recipeId) ?? null;

  function pickFood(f: FoodSummary) {
    setPicked(f);
    setWeighed("as_is");
    setYieldId(null);
    if (f.basis === "serving") {
      setUnit("serving");
      setQuantity("1");
    } else {
      setUnit("g");
      setQuantity("100");
    }
    if (f.kind === "supplement") setMeal("supplement");
  }

  const qty = parseNum(quantity);
  const calcInput: CalculateInput | null = useMemo(() => {
    if (!qty || qty <= 0) return null;
    if (mode === "food" && picked) {
      if (weighed === "cooked" && !yieldId) return null;
      return { food_id: picked.id, quantity: qty, unit, weighed_state: weighed, yield_id: weighed === "cooked" ? yieldId : null };
    }
    if (mode === "recipe" && recipeId) return { recipe_id: recipeId, quantity: qty, unit };
    return null;
  }, [mode, picked, recipeId, qty, unit, weighed, yieldId]);
  const debounced = useDebouncedValue(calcInput);
  const preview = useQuery({
    queryKey: ["calc", debounced],
    queryFn: () => api.calculate(debounced!),
    enabled: !!debounced,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () =>
      api.addLog({ ...calcInput!, meal, consumed_at: new Date(when).toISOString(), note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day"] });
      navigate("/");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (calcInput) save.mutate();
  }

  return (
    <div className="stack">
      <h1>Add entry</h1>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={mode === "food"} className={mode === "food" ? "active" : ""} onClick={() => setMode("food")}>
          Food or supplement
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "recipe"}
          className={mode === "recipe" ? "active" : ""}
          onClick={() => {
            setMode("recipe");
            setUnit("serving");
            setQuantity("1");
          }}
        >
          Recipe
        </button>
      </div>

      <form className="card stack" onSubmit={submit}>
        {mode === "food" &&
          (picked ? (
            <div className="selected">
              <div>
                <strong>{picked.name}</strong> {picked.brand && <span className="muted">· {picked.brand}</span>}
                <div className="row small">
                  <TrustBadge level={picked.trust_level} />
                  {picked.state && <span className="chip">{picked.state}</span>}
                  <span className="muted">{basisLabel(picked)}</span>
                </div>
              </div>
              <button type="button" className="btn-link" onClick={() => setPicked(null)}>
                Change
              </button>
            </div>
          ) : (
            <>
              <FoodPicker onPick={pickFood} />
              <p className="muted small">
                Can't find it? <Link to="/foods">Search online sources or add it manually</Link>.
              </p>
            </>
          ))}

        {mode === "recipe" && (
          <Field label="Recipe">
            <select
              value={recipeId ?? ""}
              onChange={(e) => {
                setRecipeId(e.target.value ? Number(e.target.value) : null);
                setUnit("serving");
              }}
            >
              <option value="">Choose a recipe…</option>
              {recipes.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {mode === "recipe" && recipes.data?.length === 0 && (
          <p className="muted">
            No recipes yet. <Link to="/recipes/new">Create one</Link>.
          </p>
        )}

        {((mode === "food" && food.data) || (mode === "recipe" && recipe)) && (
          <>
            {mode === "food" && canCook && (
              <fieldset className="fieldset">
                <legend>How did you weigh it?</legend>
                <label className="radio">
                  <input
                    type="radio"
                    checked={weighed === "as_is"}
                    onChange={() => {
                      setWeighed("as_is");
                      setYieldId(null);
                    }}
                  />
                  As described ({food.data!.state ?? "as sold"})
                </label>
                <label className="radio">
                  <input
                    type="radio"
                    checked={weighed === "cooked"}
                    onChange={() => {
                      setWeighed("cooked");
                      setUnit("g");
                    }}
                  />
                  I weighed it after cooking
                </label>
                {weighed === "cooked" && (
                  <Field label="Cooking yield" hint="Converts cooked weight back to raw weight for the nutrient calculation.">
                    {yields.data && yields.data.length === 0 ? (
                      <p className="alert alert-warn">
                        No cooking yields for this food yet. <Link to={`/foods/${picked!.id}`}>Add one on the food page</Link> (weigh it raw and cooked once).
                      </p>
                    ) : (
                      <select value={yieldId ?? ""} onChange={(e) => setYieldId(e.target.value ? Number(e.target.value) : null)} required>
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
            )}

            <div className="grid-2">
              <Field label="Amount">
                <input type="number" inputMode="decimal" min="0" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
              </Field>
              <Field label="Unit">
                <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                  {mode === "food" && food.data
                    ? unitOptions(food.data, weighed).map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))
                    : [
                        <option key="serving" value="serving">
                          servings (of {fmtNum(recipe?.servings ?? 1)})
                        </option>,
                        recipe?.cooked_weight_g ? (
                          <option key="g" value="g">
                            grams of finished dish
                          </option>
                        ) : null,
                      ]}
                </select>
              </Field>
              <Field label="Meal">
                <select value={meal} onChange={(e) => setMeal(e.target.value as Meal)}>
                  {MEALS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="When">
                <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
              </Field>
            </div>
            <Field label="Note (optional)">
              <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
            </Field>

            <section className="preview">
              <h3>Preview</h3>
              {!calcInput && <p className="muted">Enter an amount{weighed === "cooked" ? " and choose a cooking yield" : ""}.</p>}
              <ErrorBox error={preview.error} />
              {preview.data && (
                <>
                  <div className="row">
                    <TrustBadge level={preview.data.trust_level} />
                    {preview.data.grams !== null && <span className="muted">{fmtNum(preview.data.grams)} g</span>}
                  </div>
                  <MacroLine values={preview.data.nutrients} />
                  <Notes notes={preview.data.notes} />
                  <details>
                    <summary>All nutrients</summary>
                    <NutrientTable values={preview.data.nutrients} />
                  </details>
                  <ComponentList items={preview.data.other_components} />
                </>
              )}
            </section>
            <ErrorBox error={save.error} />
            <button type="submit" className="btn btn-primary" disabled={!calcInput || save.isPending}>
              {save.isPending ? "Saving…" : "Log it"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
