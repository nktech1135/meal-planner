import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components/common";
import { LEAVE_WARNING, parseNum, useLeaveWarning, useNutrients } from "../lib";
import type { Basis, Component, Food, FoodInput, FoodState, Kind } from "../types";
import { Button, rescueFocus, VisuallyHidden } from "../components/a11y";

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
  portions: { id?: number; label: string; gram_weight: string }[];
  // nutrient_code: the nutrient a label amount belongs to when its conversion depends on the form (e.g.
  // vitamin A in IU), so it can be converted once the form is chosen. note: kept from imported labels.
  other_components: { name: string; amount: string; unit: string; nutrient_code: string; note?: string | null }[];
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
    portions: f.portions.map((p) => ({ id: p.id, label: p.label, gram_weight: String(p.gram_weight) })),
    other_components: f.other_components.map((c) => ({
      name: c.name,
      amount: s(c.amount),
      unit: c.unit ?? "",
      nutrient_code: c.nutrient_code ?? "",
      note: c.note,
    })),
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
      .map((p) => ({ id: p.id, label: p.label.trim(), gram_weight: parseNum(p.gram_weight) ?? 0 }))
      .filter((p) => p.label && p.gram_weight > 0),
    other_components: s.other_components
      .filter((c) => c.name.trim())
      .map(
        (c): Component => ({
          name: c.name.trim(),
          amount: parseNum(c.amount),
          unit: c.unit.trim() || null,
          nutrient_code: c.nutrient_code || null,
          ...(c.note ? { note: c.note } : {}),
        }),
      ),
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
  // From the supplement check (?kind=supplement): start a supplement label, counted per serving.
  const [initial, setInitial] = useState<FormState>(() => ({
    ...EMPTY,
    barcode: params.get("barcode") ?? "",
    ...(params.get("kind") === "supplement" ? { kind: "supplement" as Kind, basis: "serving" as Basis, serving_quantity: "1" } : {}),
  }));
  const [form, setForm] = useState<FormState>(initial);

  useEffect(() => {
    if (existing.data) {
      const loaded = fromFood(existing.data);
      setInitial(loaded);
      setForm(loaded);
    }
  }, [existing.data]);

  const save = useMutation({
    mutationFn: (input: FoodInput) => (editing ? api.updateFood(editing, input) : api.createFood(input)),
    onSuccess: (food) => {
      qc.invalidateQueries({ queryKey: ["foods"] });
      // Everywhere this food's numbers show: its page (also as read for a shared plan), its form choices,
      // and the recipes, plans and calculations that use it.
      qc.invalidateQueries({ queryKey: ["food", food.id] });
      qc.invalidateQueries({ queryKey: ["food-forms", food.id] });
      for (const key of ["recipe", "recipes", "plan", "calc", "supplement-stack", "supplement-check"]) qc.invalidateQueries({ queryKey: [key] });
      qc.setQueryData(["food", food.id], food);
      setInitial(form);
      navigate(`/foods/${food.id}`);
    },
  });
  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(initial), [form, initial]) && !save.isSuccess;
  useLeaveWarning(dirty);
  const formNutrients = useMemo(() => nutrientDefs.filter((n) => n.category === "vitamin" || n.category === "mineral"), [nutrientDefs]);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(toInput(form));
  }

  if (editing && existing.isLoading)
    return (
      <div className="stack">
        <h1>Edit food</h1>
        <Loading />
      </div>
    );
  if (editing && existing.data && existing.data.owner_id === null) {
    return (
      <div className="stack">
        <h1>Edit food</h1>
        <div className="alert alert-warn">Imported foods are read-only. Use "Copy to edit" on the food page.</div>
      </div>
    );
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
        {form.portions.length > 0 && (
          <div className="row row-head muted small" aria-hidden="true">
            <span className="grow">Label</span>
            <span className="w-sm">Grams</span>
            <span className="btn-link row-head-spacer">Remove</span>
          </div>
        )}
        {form.portions.map((p, i) => (
          <div key={i} className="row">
            <input
              className="grow"
              placeholder="e.g. 1 cup, chopped"
              value={p.label}
              onChange={(e) => set("portions", form.portions.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
              aria-label={`Portion ${i + 1}: label`}
            />
            <input
              type="number"
              step="any"
              min="0"
              placeholder="grams"
              value={p.gram_weight}
              onChange={(e) => set("portions", form.portions.map((x, j) => (j === i ? { ...x, gram_weight: e.target.value } : x)))}
              aria-label={`Portion ${i + 1}: grams`}
              className="w-sm"
            />
            <button
              type="button"
              className="btn-link danger"
              onClick={() => {
                set("portions", form.portions.filter((_, j) => j !== i));
                rescueFocus(() => document.getElementById("add-portion"));
              }}
            >
              Remove<VisuallyHidden> portion {i + 1}{p.label ? ` (${p.label})` : ""}</VisuallyHidden>
            </button>
          </div>
        ))}
        <button id="add-portion" type="button" className="btn" onClick={() => set("portions", [...form.portions, { label: "", gram_weight: "" }])}>
          <span aria-hidden="true">+</span> Add portion
        </button>
      </section>

      {form.kind === "supplement" && (
        <section className="card stack">
          <h2>Other label components</h2>
          <p className="muted small">
            Ingredients that aren't in the nutrient list (e.g. botanicals, creatine), {basisText}. For a vitamin or mineral given in a unit
            that depends on its form (e.g. vitamin A or E in IU), choose the nutrient under "Counts toward"; you can then pick the form on the
            food's page and it's counted.
          </p>
          {form.other_components.length > 0 && (
            <div className="row row-head muted small" aria-hidden="true">
              <span className="grow">Name</span>
              <span className="w-sm">Amount</span>
              <span className="w-sm">Unit</span>
              <span className="w-md">Counts toward</span>
              <span className="btn-link row-head-spacer">Remove</span>
            </div>
          )}
          {form.other_components.map((c, i) => (
            <div key={i} className="row">
              <input
                className="grow"
                placeholder="e.g. Ashwagandha root extract"
                value={c.name}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                aria-label={`Component ${i + 1}: name`}
              />
              <input
                type="number"
                step="any"
                className="w-sm"
                placeholder="Amount"
                value={c.amount}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))}
                aria-label={`Component ${i + 1}: amount`}
              />
              <input
                className="w-sm"
                placeholder="Unit"
                value={c.unit}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))}
                aria-label={`Component ${i + 1}: unit`}
              />
              <select
                className="w-md"
                value={c.nutrient_code}
                onChange={(e) => set("other_components", form.other_components.map((x, j) => (j === i ? { ...x, nutrient_code: e.target.value } : x)))}
                aria-label={`Component ${i + 1}: counts toward`}
              >
                <option value="">Not a listed nutrient</option>
                {formNutrients.map((n) => (
                  <option key={n.code} value={n.code}>
                    {n.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn-link danger"
                onClick={() => {
                  set("other_components", form.other_components.filter((_, j) => j !== i));
                  rescueFocus(() => document.getElementById("add-component"));
                }}
              >
                Remove<VisuallyHidden> component {i + 1}{c.name ? ` (${c.name})` : ""}</VisuallyHidden>
              </button>
            </div>
          ))}
          <button
            id="add-component"
            type="button"
            className="btn"
            onClick={() => set("other_components", [...form.other_components, { name: "", amount: "", unit: "mg", nutrient_code: "" }])}
          >
            <span aria-hidden="true">+</span> Add component
          </button>
        </section>
      )}

      <ErrorBox error={save.error} />
      <div className="row">
        <Button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save food"}
        </Button>
        <button type="button" className="btn" onClick={() => (!dirty || confirm(LEAVE_WARNING)) && navigate(-1)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
