import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components/common";
import { parseNum, useNutrients } from "../lib";
import type { Basis, Component, Food, FoodInput, FoodState, Kind } from "../types";

const CATEGORY_TITLES: Record<string, string> = {
  energy: "Energy",
  macro: "Macronutrients",
  carb: "Carbohydrate detail",
  lipid: "Fat detail",
  vitamin: "Vitamins",
  mineral: "Minerals",
  other: "Other",
};

interface FormState {
  name: string;
  brand: string;
  kind: Kind;
  state: FoodState | "";
  cooking_method: string;
  basis: Basis;
  serving_quantity: string;
  serving_unit: string;
  serving_size_g: string;
  citation: string;
  barcode: string;
  ingredients: string;
  nutrients: Record<string, string>;
  portions: { label: string; gram_weight: string }[];
  other_components: { name: string; amount: string; unit: string }[];
}

const EMPTY: FormState = {
  name: "",
  brand: "",
  kind: "food",
  state: "",
  cooking_method: "",
  basis: "100g",
  serving_quantity: "",
  serving_unit: "",
  serving_size_g: "",
  citation: "",
  barcode: "",
  ingredients: "",
  nutrients: {},
  portions: [],
  other_components: [],
};

function fromFood(f: Food): FormState {
  const s = (v: number | null) => (v === null || v === undefined ? "" : String(v));
  return {
    name: f.name,
    brand: f.brand ?? "",
    kind: f.kind,
    state: f.state ?? "",
    cooking_method: f.cooking_method ?? "",
    basis: f.basis,
    serving_quantity: s(f.serving_quantity),
    serving_unit: f.serving_unit ?? "",
    serving_size_g: s(f.serving_size_g),
    citation: f.citation ?? "",
    barcode: f.barcode ?? "",
    ingredients: f.ingredients ?? "",
    nutrients: Object.fromEntries(Object.entries(f.nutrients).map(([k, v]) => [k, String(v)])),
    portions: f.portions.map((p) => ({ label: p.label, gram_weight: String(p.gram_weight) })),
    other_components: f.other_components.map((c) => ({ name: c.name, amount: s(c.amount), unit: c.unit ?? "" })),
  };
}

function toInput(s: FormState): FoodInput {
  const nutrients: Record<string, number> = {};
  for (const [k, v] of Object.entries(s.nutrients)) {
    const n = parseNum(v);
    if (n !== null) nutrients[k] = n;
  }
  return {
    name: s.name.trim(),
    brand: s.brand.trim() || null,
    kind: s.kind,
    state: s.state || null,
    cooking_method: s.cooking_method.trim() || null,
    basis: s.basis,
    serving_quantity: parseNum(s.serving_quantity),
    serving_unit: s.serving_unit.trim() || null,
    serving_size_g: parseNum(s.serving_size_g),
    citation: s.citation.trim() || null,
    barcode: s.barcode.trim() || null,
    ingredients: s.ingredients.trim() || null,
    nutrients,
    portions: s.portions
      .map((p) => ({ label: p.label.trim(), gram_weight: parseNum(p.gram_weight) ?? 0 }))
      .filter((p) => p.label && p.gram_weight > 0),
    other_components: s.other_components
      .filter((c) => c.name.trim())
      .map((c): Component => ({ name: c.name.trim(), amount: parseNum(c.amount), unit: c.unit.trim() || null })),
  };
}

export default function FoodFormPage() {
  const { id } = useParams();
  const editing = id ? Number(id) : null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { list: nutrientDefs } = useNutrients();
  const existing = useQuery({ queryKey: ["food", editing], queryFn: () => api.food(editing!), enabled: !!editing });
  const [params] = useSearchParams();
  // Arriving from a barcode scan that found nothing: start with the scanned barcode filled in.
  const [form, setForm] = useState<FormState>(() => ({ ...EMPTY, barcode: params.get("barcode") ?? "" }));

  useEffect(() => {
    if (existing.data) setForm(fromFood(existing.data));
  }, [existing.data]);

  const save = useMutation({
    mutationFn: (input: FoodInput) => (editing ? api.updateFood(editing, input) : api.createFood(input)),
    onSuccess: (food) => {
      qc.invalidateQueries({ queryKey: ["foods"] });
      qc.setQueryData(["food", food.id], food);
      navigate(`/foods/${food.id}`);
    },
  });

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(toInput(form));
  }

  if (editing && existing.isLoading) return <Loading />;
  if (editing && existing.data && existing.data.owner_id === null) {
    return <div className="alert alert-warn">Imported foods are read-only. Use "Copy to edit" on the food page.</div>;
  }

  const categories = Array.from(new Set(nutrientDefs.map((n) => n.category)));
  const basisText = form.basis === "100g" ? "per 100 g" : "per serving";

  return (
    <form className="stack" onSubmit={submit}>
      <h1>{editing ? "Edit food" : "New food"}</h1>
      <ErrorBox error={existing.error} />
      <section className="card stack">
        <div className="grid-2">
          <Field label="Name">
            <input required maxLength={300} value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Brand">
            <input value={form.brand} onChange={(e) => set("brand", e.target.value)} />
          </Field>
          <Field label="Kind">
            <select value={form.kind} onChange={(e) => set("kind", e.target.value as Kind)}>
              <option value="food">Food</option>
              <option value="supplement">Supplement</option>
            </select>
          </Field>
          <Field label="State" hint="Raw foods can be logged by cooked weight once they have a cooking yield.">
            <select value={form.state} onChange={(e) => set("state", e.target.value as FoodState | "")}>
              <option value="">Not applicable</option>
              <option value="raw">Raw</option>
              <option value="cooked">Cooked</option>
              <option value="prepared">Prepared</option>
            </select>
          </Field>
          {form.state === "cooked" && (
            <Field label="Cooking method">
              <input value={form.cooking_method} onChange={(e) => set("cooking_method", e.target.value)} placeholder="e.g. roasted" />
            </Field>
          )}
          <Field label="Values are given">
            <select value={form.basis} onChange={(e) => set("basis", e.target.value as Basis)}>
              <option value="100g">Per 100 g</option>
              <option value="serving">Per serving (labels, supplements)</option>
            </select>
          </Field>
        </div>
        <div className="grid-3">
          {form.basis === "serving" && (
            <>
              <Field label="Units per serving">
                <input type="number" step="any" min="0" value={form.serving_quantity} onChange={(e) => set("serving_quantity", e.target.value)} placeholder="e.g. 2" />
              </Field>
              <Field label="Unit name">
                <input value={form.serving_unit} onChange={(e) => set("serving_unit", e.target.value)} placeholder="e.g. capsules" />
              </Field>
            </>
          )}
          <Field label="Serving weight (g)" hint="Optional; lets you log by servings or grams.">
            <input type="number" step="any" min="0" value={form.serving_size_g} onChange={(e) => set("serving_size_g", e.target.value)} />
          </Field>
        </div>
        <Field label="Where do these values come from?" hint="e.g. 'Package label, photographed 2026-10-30'. Manual entries are marked as user data.">
          <input maxLength={1000} value={form.citation} onChange={(e) => set("citation", e.target.value)} />
        </Field>
        <div className="grid-2">
          <Field label="Barcode" hint="Optional. Scanning this barcode later finds this food.">
            <input inputMode="numeric" maxLength={32} value={form.barcode} onChange={(e) => set("barcode", e.target.value)} />
          </Field>
          <Field label="Ingredients" hint="Optional, from the label.">
            <textarea rows={2} maxLength={5000} value={form.ingredients} onChange={(e) => set("ingredients", e.target.value)} />
          </Field>
        </div>
      </section>

      <section className="card stack">
        <h2>Nutrients ({basisText})</h2>
        <p className="muted small">Leave blank when unknown — blank is not zero.</p>
        {categories.map((cat) => (
          <fieldset key={cat} className="fieldset">
            <legend>{CATEGORY_TITLES[cat] ?? cat}</legend>
            <div className="grid-3">
              {nutrientDefs
                .filter((n) => n.category === cat)
                .map((n) => (
                  <Field key={n.code} label={`${n.name} (${n.unit})`}>
                    <input
                      type="number"
                      inputMode="decimal"
                      step="any"
                      min="0"
                      value={form.nutrients[n.code] ?? ""}
                      onChange={(e) => set("nutrients", { ...form.nutrients, [n.code]: e.target.value })}
                    />
                  </Field>
                ))}
            </div>
          </fieldset>
        ))}
      </section>

      <section className="card stack">
        <h2>Portions</h2>
        <p className="muted small">Household measures with their weight, e.g. "1 cup, chopped" = 128 g.</p>
        {form.portions.map((p, i) => (
          <div key={i} className="row">
            <input
              className="grow"
              placeholder="Label"
              value={p.label}
              onChange={(e) => set("portions", form.portions.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
              aria-label="Portion label"
            />
            <input
              type="number"
              step="any"
              min="0"
              placeholder="grams"
              value={p.gram_weight}
              onChange={(e) => set("portions", form.portions.map((x, j) => (j === i ? { ...x, gram_weight: e.target.value } : x)))}
              aria-label="Portion grams"
              className="w-sm"
            />
            <button type="button" className="btn-link danger" onClick={() => set("portions", form.portions.filter((_, j) => j !== i))}>
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="btn" onClick={() => set("portions", [...form.portions, { label: "", gram_weight: "" }])}>
          + Add portion
        </button>
      </section>

      {form.kind === "supplement" && (
        <section className="card stack">
          <h2>Other label components</h2>
          <p className="muted small">Ingredients that aren't in the nutrient list (e.g. botanicals, creatine), {basisText}.</p>
          {form.other_components.map((c, i) => (
            <div key={i} className="row wrap">
              <input
                className="grow"
                placeholder="Name"
                value={c.name}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                aria-label="Component name"
              />
              <input
                type="number"
                step="any"
                className="w-sm"
                placeholder="Amount"
                value={c.amount}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))}
                aria-label="Component amount"
              />
              <input
                className="w-sm"
                placeholder="Unit"
                value={c.unit}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))}
                aria-label="Component unit"
              />
              <button type="button" className="btn-link danger" onClick={() => set("other_components", form.other_components.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          <button type="button" className="btn" onClick={() => set("other_components", [...form.other_components, { name: "", amount: "", unit: "mg" }])}>
            + Add component
          </button>
        </section>
      )}

      <ErrorBox error={save.error} />
      <div className="row">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save food"}
        </button>
        <button type="button" className="btn" onClick={() => navigate(-1)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
