import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { QuantityFields, unitChoices, WeighedFields } from "../components/AmountFields";
import { ComponentList, ErrorBox, Field, MacroLine, Notes, NutrientTable } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { SavedMeals } from "../components/SavedMeals";
import { TrustBadge } from "../components/TrustBadge";
import { basisLabel, defaultMeal, fmtNum, mealLabel, nowLocalInput, parseNum, unitText } from "../lib";
import { MEALS, type CalculateInput, type FoodSummary, type LogEntry, type Meal, type Suggestion, type WeighedState } from "../types";
import { Button, focusSoon, rescueFocus, tabPanelProps, TabList, useAnnounceText, VisuallyHidden } from "../components/a11y";

function useDebouncedValue<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Mode = "food" | "recipe" | "saved";

function SuggestionItem({
  s,
  onLog,
  onAdjust,
  busy,
}: {
  s: Suggestion;
  onLog: () => void;
  onAdjust: () => void;
  busy: boolean;
}) {
  const amount = `${fmtNum(s.quantity)} ${unitText(s.unit)}${s.weighed_state === "cooked" ? " cooked" : ""}`;
  return (
    <li className="suggestion">
      <div className="suggestion-main">
        <strong className="suggestion-label">{s.label}</strong>
        <div className="row wrap small">
          <TrustBadge level={s.trust_level} />
          {s.kind === "recipe" && <span className="chip">recipe</span>}
          {s.kind === "supplement" && <span className="chip">supplement</span>}
          <span className="muted">last: {amount}</span>
          {s.energy_kcal !== null && <span className="muted">· {Math.round(s.energy_kcal)} kcal</span>}
          <span className="muted">· used {s.times}×</span>
        </div>
      </div>
      <div className="suggestion-actions">
        <Button type="button" className="btn btn-primary btn-sm" onClick={onLog} disabled={busy}>
          Log again<VisuallyHidden>{s.label}, {amount}</VisuallyHidden>
        </Button>
        <button type="button" className="btn btn-sm" onClick={onAdjust} aria-label={`Adjust ${s.label} before logging`}>
          Adjust…
        </button>
      </div>
    </li>
  );
}

export default function AddEntryPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("food");
  const [picked, setPicked] = useState<FoodSummary | null>(null);
  const [recipeId, setRecipeId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("100");
  const [unit, setUnit] = useState("g");
  const [weighed, setWeighed] = useState<WeighedState>("as_is");
  const [yieldId, setYieldId] = useState<number | null>(null);
  const [meal, setMeal] = useState<Meal>(defaultMeal);
  const [savedMeal, setSavedMeal] = useState<Meal | "">("");
  const [when, setWhen] = useState(nowLocalInput);
  const [note, setNote] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [logged, setLogged] = useState<LogEntry | null>(null);
  const [undone, setUndone] = useState<string | null>(null);
  const noticeRef = useAnnounceText<HTMLDivElement>();
  const selectedRef = useRef<HTMLDivElement>(null);
  const onQueryChange = useCallback((q: string) => setSearchQ(q), []);

  const food = useQuery({ queryKey: ["food", picked?.id], queryFn: () => api.food(picked!.id), enabled: !!picked });
  const recipes = useQuery({ queryKey: ["recipes"], queryFn: () => api.recipes(), enabled: mode === "recipe" });
  const recipe = recipes.data?.find((r) => r.id === recipeId) ?? null;
  const showSuggestions = mode === "food" && !picked;
  const suggestions = useQuery({
    queryKey: ["suggestions", meal, searchQ],
    queryFn: () => api.suggestions(meal, searchQ, searchQ ? 6 : 12),
    enabled: showSuggestions,
    placeholderData: (prev) => prev,
  });

  function pickFood(f: FoodSummary, focus = true) {
    setPicked(f);
    // The list that had focus is replaced by the chosen food; start reading there.
    if (focus) focusSoon(() => selectedRef.current);
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
    mutationFn: () => api.addLog({ ...calcInput!, meal, consumed_at: new Date(when).toISOString(), note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      navigate("/");
    },
  });

  const again = useMutation({
    mutationFn: (s: Suggestion) =>
      api.addLog({
        food_id: s.food_id,
        recipe_id: s.recipe_id,
        quantity: s.quantity,
        unit: s.unit,
        weighed_state: s.weighed_state,
        yield_id: s.yield_id,
        meal,
        consumed_at: new Date(when).toISOString(),
      }),
    onMutate: () => {
      setLogged(null);
      setUndone(null);
    },
    onSuccess: (entry) => {
      setLogged(entry);
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });
  const undo = useMutation({
    mutationFn: (e: LogEntry) => api.deleteLog(e.id),
    onSuccess: (_, e) => {
      setLogged(null);
      setUndone(`Undone: removed ${e.label} from the log.`);
      rescueFocus(() => noticeRef.current);
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });

  const adjust = useMutation({
    mutationFn: async (s: Suggestion) => {
      if (s.food_id) {
        const f = await qc.fetchQuery({ queryKey: ["food", s.food_id], queryFn: () => api.food(s.food_id!) });
        setMode("food");
        setPicked(f);
      } else {
        setMode("recipe");
        setRecipeId(s.recipe_id);
      }
      setQuantity(String(s.quantity));
      setUnit(s.unit);
      setWeighed(s.weighed_state);
      setYieldId(s.yield_id);
      setLogged(null);
      setUndone(null);
      focusSoon(() => selectedRef.current ?? document.getElementById("entry-recipe"));
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (calcInput) save.mutate();
  }

  function switchMode(m: Mode) {
    setMode(m);
    if (m === "recipe") {
      setUnit("serving");
      setQuantity("1");
      setWeighed("as_is");
      setYieldId(null);
    } else if (m === "food" && picked) {
      pickFood(picked, false);
    }
  }

  const suggestionList = (heading: string) =>
    suggestions.data && suggestions.data.length > 0 ? (
      <section className="suggestions" aria-label={heading}>
        <h2 className="h-sm">{heading}</h2>
        <ul className="plain-list">
          {suggestions.data.map((s) => (
            <SuggestionItem
              key={`${s.food_id ?? ""}-${s.recipe_id ?? ""}`}
              s={s}
              busy={again.isPending}
              onLog={() => again.mutate(s)}
              onAdjust={() => adjust.mutate(s)}
            />
          ))}
        </ul>
      </section>
    ) : null;

  return (
    <div className="stack">
      <h1>Add entry</h1>
      <TabList
        id="add-entry"
        label="What to add"
        value={mode}
        onChange={switchMode}
        tabs={[
          { value: "food", label: "Food or supplement" },
          { value: "recipe", label: "Recipe" },
          { value: "saved", label: "Saved meals" },
        ]}
      />

      <div className="card stack" {...tabPanelProps("add-entry", mode)}>
        <div className="grid-2">
          <Field label="Meal">
            {mode === "saved" ? (
              <select value={savedMeal} onChange={(e) => setSavedMeal(e.target.value as Meal | "")}>
                <option value="">Each saved meal's usual meal</option>
                {MEALS.map((m) => (
                  <option key={m} value={m}>
                    {mealLabel(m)}
                  </option>
                ))}
              </select>
            ) : (
              <select value={meal} onChange={(e) => setMeal(e.target.value as Meal)}>
                {MEALS.map((m) => (
                  <option key={m} value={m}>
                    {mealLabel(m)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="When">
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
          </Field>
        </div>

        {logged && (
          <div ref={noticeRef} className="result result-ok">
            <span aria-hidden="true">✓</span> Logged {logged.label} ({fmtNum(logged.quantity)} {unitText(logged.unit)}) to {logged.meal}.{" "}
            <Button type="button" className="btn-link" onClick={() => undo.mutate(logged)} disabled={undo.isPending}>
              Undo<VisuallyHidden> logging {logged.label}</VisuallyHidden>
            </Button>{" "}
            <Link to="/">View day</Link>
          </div>
        )}
        {undone && !logged && (
          <div ref={noticeRef} className="result result-info">
            {undone}
          </div>
        )}
        <ErrorBox error={again.error || adjust.error || undo.error} />

        {mode === "saved" && <SavedMeals logMeal={savedMeal} when={when} />}

        {mode !== "saved" && (
          <form className="stack" onSubmit={submit}>
            {mode === "food" &&
              (picked ? (
                <div className="selected" ref={selectedRef} tabIndex={-1} aria-label={`Chosen: ${picked.name}`} role="group">
                  <div className="min-0">
                    <strong>{picked.name}</strong> {picked.brand && <span className="muted">· {picked.brand}</span>}
                    <div className="row wrap small">
                      <TrustBadge level={picked.trust_level} />
                      {picked.state && <span className="chip">{picked.state}</span>}
                      <span className="muted">{basisLabel(picked)}</span>
                    </div>
                  </div>
                  <button type="button" className="btn-link" onClick={() => setPicked(null)}>
                    Change<VisuallyHidden> food</VisuallyHidden>
                  </button>
                </div>
              ) : (
                <>
                  <FoodPicker onPick={pickFood} onQueryChange={onQueryChange} beforeResults={suggestionList("From your log")} />
                  {!searchQ && suggestionList(`Your usual for ${meal}`)}
                  {!searchQ && suggestions.data?.length === 0 && (
                    <p className="muted small">Things you log will show up here for one-click logging next time.</p>
                  )}
                  <p className="muted small">
                    Can't find it? <Link to="/foods">Search online sources or add it manually</Link>.
                  </p>
                </>
              ))}

            {mode === "recipe" && (
              <Field label="Recipe">
                <select
                  id="entry-recipe"
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
                {mode === "food" && food.data && (
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
                  options={unitChoices(mode === "food" ? food.data : null, mode === "recipe" ? recipe : null, weighed, unit)}
                  onQuantity={setQuantity}
                  onUnit={setUnit}
                />
                <Field label="Note (optional)">
                  <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
                </Field>

                <section className="preview" aria-labelledby="preview-title">
                  <h2 id="preview-title" className="h3">
                    Preview
                  </h2>
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
                        <NutrientTable values={preview.data.nutrients} caption="All nutrients for this amount" />
                      </details>
                      <ComponentList items={preview.data.other_components} />
                    </>
                  )}
                </section>
                <ErrorBox error={save.error} />
                <Button type="submit" className="btn btn-primary" disabled={!calcInput || save.isPending}>
                  {save.isPending ? "Saving…" : "Log it"}
                </Button>
              </>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
