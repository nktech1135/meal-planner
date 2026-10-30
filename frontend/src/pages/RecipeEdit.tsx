import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ComponentList, ErrorBox, Field, Loading, MacroLine, Notes, NutrientTable } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { TrustBadge } from "../components/TrustBadge";
import { fmtNum, parseNum } from "../lib";
import type { Recipe, RecipeInput, WeighedState } from "../types";
import { Button, rescueFocus, useAnnounce, usePageTitle, VisuallyHidden } from "../components/a11y";

interface Row {
  food_id: number;
  food_name: string;
  food_state: string | null;
  grams: string;
  weighed_state: WeighedState;
  yield_id: number | null;
  note: string;
}

function IngredientRow({ row, onChange, onRemove }: { row: Row; onChange: (r: Row) => void; onRemove: () => void }) {
  const canCook = row.food_state !== "cooked";
  const yields = useQuery({
    queryKey: ["yields", row.food_id],
    queryFn: () => api.yields(row.food_id),
    enabled: row.weighed_state === "cooked",
  });
  return (
    <li className="ingredient">
      <div className="row between">
        <h3 className="h-card">
          <Link to={`/foods/${row.food_id}`}>{row.food_name}</Link>
        </h3>
        <button type="button" className="btn-link danger" onClick={onRemove}>
          Remove<VisuallyHidden> {row.food_name}</VisuallyHidden>
        </button>
      </div>
      <div className="row wrap">
        <label className="inline">
          <input
            type="number"
            step="any"
            min="0"
            required
            className="w-sm"
            value={row.grams}
            onChange={(e) => onChange({ ...row, grams: e.target.value })}
            aria-label={`Grams of ${row.food_name}`}
          />{" "}
          <span aria-hidden="true">g</span>
        </label>
        {canCook && (
          <select
            value={row.weighed_state}
            onChange={(e) => onChange({ ...row, weighed_state: e.target.value as WeighedState, yield_id: null })}
            aria-label={`How ${row.food_name} was weighed`}
          >
            <option value="as_is">weighed as described{row.food_state ? ` (${row.food_state})` : ""}</option>
            <option value="cooked">weighed after cooking</option>
          </select>
        )}
        {row.weighed_state === "cooked" &&
          (yields.data && yields.data.length === 0 ? (
            <span className="warn-text small">
              No yields — <Link to={`/foods/${row.food_id}`}>add one<VisuallyHidden> for {row.food_name}</VisuallyHidden></Link>
            </span>
          ) : (
            <select
              required
              value={row.yield_id ?? ""}
              onChange={(e) => onChange({ ...row, yield_id: e.target.value ? Number(e.target.value) : null })}
              aria-label={`Cooking yield for ${row.food_name}`}
            >
              <option value="">Choose yield…</option>
              {yields.data?.map((y) => (
                <option key={y.id} value={y.id}>
                  {y.method} ×{fmtNum(y.yield_factor, 3)} ({y.basis})
                </option>
              ))}
            </select>
          ))}
        <input
          className="grow"
          placeholder="note (optional)"
          maxLength={200}
          value={row.note}
          onChange={(e) => onChange({ ...row, note: e.target.value })}
          aria-label={`Note for ${row.food_name} (optional)`}
          title="Note (optional)"
        />
      </div>
    </li>
  );
}

function NutritionPanel({ recipe }: { recipe: Recipe }) {
  const n = recipe.nutrition;
  if (!n) return null;
  if ("error" in n) return <div className="alert alert-error">{n.error}</div>;
  return (
    <section className="card stack">
      <div className="row between">
        <h2>Nutrition</h2>
        <TrustBadge level={n.trust_level} />
      </div>
      <div>
        <h3>Per serving (1 of {fmtNum(recipe.servings)})</h3>
        <MacroLine values={n.per_serving} />
      </div>
      {n.per_100g_cooked && (
        <div>
          <h3>Per 100 g of finished dish</h3>
          <MacroLine values={n.per_100g_cooked} />
        </div>
      )}
      <div className="small muted">
        Ingredient mass (raw equivalent): {fmtNum(n.ingredient_mass_g)} g
        {recipe.cooked_weight_g ? ` → cooked ${fmtNum(recipe.cooked_weight_g)} g` : ""}
      </div>
      <Notes notes={n.notes} />
      <details>
        <summary>All nutrients per serving</summary>
        <NutrientTable values={n.per_serving} />
      </details>
      <details>
        <summary>Whole recipe</summary>
        <NutrientTable values={n.total} />
      </details>
      <ComponentList items={n.other_components} />
    </section>
  );
}

export default function RecipeEditPage() {
  const { id } = useParams();
  const recipeId = id ? Number(id) : null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const existing = useQuery({ queryKey: ["recipe", recipeId], queryFn: () => api.recipe(recipeId!), enabled: !!recipeId });

  const [name, setName] = useState("");
  const [servings, setServings] = useState("1");
  const [cookedWeight, setCookedWeight] = useState("");
  const [notes, setNotes] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const r = existing.data;
    if (!r) return;
    setName(r.name);
    setServings(String(r.servings));
    setCookedWeight(r.cooked_weight_g ? String(r.cooked_weight_g) : "");
    setNotes(r.notes);
    setRows(
      r.ingredients.map((i) => ({
        food_id: i.food_id,
        food_name: i.food_name,
        food_state: null,
        grams: String(i.grams),
        weighed_state: i.weighed_state,
        yield_id: i.yield_id,
        note: i.note,
      })),
    );
    setDirty(false);
  }, [existing.data]);

  const announce = useAnnounce();
  usePageTitle(existing.data?.name);
  const save = useMutation({
    mutationFn: (body: RecipeInput) => (recipeId ? api.updateRecipe(recipeId, body) : api.createRecipe(body)),
    onSuccess: (r) => {
      announce(`Saved ${r.name}. Nutrition is updated.`);
      qc.invalidateQueries({ queryKey: ["recipes"] });
      qc.setQueryData(["recipe", r.id], r);
      setDirty(false);
      if (!recipeId) navigate(`/recipes/${r.id}`, { replace: true });
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteRecipe(recipeId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recipes"] });
      navigate("/recipes");
    },
  });

  const edit = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setDirty(true);
  };

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({
      name: name.trim(),
      servings: parseNum(servings) ?? 1,
      cooked_weight_g: parseNum(cookedWeight),
      notes,
      ingredients: rows.map((r) => ({
        food_id: r.food_id,
        grams: parseNum(r.grams) ?? 0,
        weighed_state: r.weighed_state,
        yield_id: r.weighed_state === "cooked" ? r.yield_id : null,
        note: r.note,
      })),
    });
  }

  if (recipeId && existing.isLoading)
    return (
      <div className="stack">
        <h1>Edit recipe</h1>
        <Loading />
      </div>
    );

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{recipeId ? "Edit recipe" : "New recipe"}</h1>
        {recipeId && (
          <button
            type="button"
            className="btn danger"
            onClick={() => {
              if (confirm("Delete this recipe? Past log entries keep their recorded nutrients.")) del.mutate();
            }}
          >
            Delete<VisuallyHidden> recipe</VisuallyHidden>
          </button>
        )}
      </div>
      <ErrorBox error={existing.error || del.error} />
      <form className="card stack" onSubmit={submit}>
        <div className="grid-3">
          <Field label="Name">
            <input required maxLength={200} value={name} onChange={(e) => edit(setName)(e.target.value)} />
          </Field>
          <Field label="Servings">
            <input type="number" step="any" min="0" required value={servings} onChange={(e) => edit(setServings)(e.target.value)} />
          </Field>
          <Field label="Cooked weight (g)" hint="Weigh the finished dish (without the pot).">
            <input type="number" step="any" min="0" value={cookedWeight} onChange={(e) => edit(setCookedWeight)(e.target.value)} />
          </Field>
        </div>
        <h2 id="ingredients-title">Ingredients</h2>
        <ul className="plain-list stack">
          {rows.map((r, i) => (
            <IngredientRow
              key={`${r.food_id}-${i}`}
              row={r}
              onChange={(nr) => edit(setRows)(rows.map((x, j) => (j === i ? nr : x)))}
              onRemove={() => {
                edit(setRows)(rows.filter((_, j) => j !== i));
                announce(`Removed ${r.food_name}.`);
                rescueFocus(() => document.getElementById("ingredients-title"));
              }}
            />
          ))}
        </ul>
        <FoodPicker
          placeholder="Add an ingredient…"
          onPick={(f) => {
            edit(setRows)([
              ...rows,
              { food_id: f.id, food_name: f.name, food_state: f.state, grams: "100", weighed_state: "as_is", yield_id: null, note: "" },
            ]);
            announce(`Added ${f.name}, 100 g. Ingredients: ${rows.length + 1}.`);
          }}
        />
        <Field label="Notes">
          <textarea rows={3} maxLength={4000} value={notes} onChange={(e) => edit(setNotes)(e.target.value)} />
        </Field>
        <ErrorBox error={save.error} />
        <div className="row">
          <Button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save recipe"}
          </Button>
          {dirty && existing.data && <span className="muted small">Unsaved changes — save to update nutrition.</span>}
        </div>
      </form>
      {(save.data ?? existing.data) && <NutritionPanel recipe={(save.data ?? existing.data)!} />}
    </div>
  );
}
