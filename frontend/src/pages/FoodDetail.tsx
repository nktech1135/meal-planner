import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComponentList, ErrorBox, Field, Loading, NutrientTable, ResultNote } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { TrustBadge, TRUST_INFO } from "../components/TrustBadge";
import { basisLabel, fmtNum, parseNum, SOURCE_NAMES, useNutrients } from "../lib";
import type { DerivedYield, Food, FoodSummary, FormRow, YieldInput } from "../types";

type YieldMode = "measured" | "published" | "derived";

function AddYield({ food, onDone }: { food: Food; onDone: () => void }) {
  const { list: nutrientDefs } = useNutrients();
  const [mode, setMode] = useState<YieldMode>("measured");
  const [method, setMethod] = useState("");
  const [rawG, setRawG] = useState("");
  const [cookedG, setCookedG] = useState("");
  const [factor, setFactor] = useState("");
  const [citation, setCitation] = useState("");
  const [notes, setNotes] = useState("");
  const [cooked, setCooked] = useState<FoodSummary | null>(null);
  const [derived, setDerived] = useState<DerivedYield | null>(null);
  const [retention, setRetention] = useState<{ code: string; value: string }[]>([]);

  const derive = useMutation({
    mutationFn: (c: FoodSummary) => api.deriveYield(food.id, c.id),
    onSuccess: (d) => setDerived(d),
  });
  const save = useMutation({ mutationFn: api.createYield, onSuccess: onDone });

  function submit(e: FormEvent) {
    e.preventDefault();
    const ret: Record<string, number> = {};
    for (const r of retention) {
      const v = parseNum(r.value);
      if (r.code && v !== null) ret[r.code] = v;
    }
    const body: YieldInput = { raw_food_id: food.id, method: method.trim(), basis: mode, retention: ret, notes: notes.trim() || null };
    if (mode === "measured") {
      body.raw_weight_g = parseNum(rawG);
      body.cooked_weight_g = parseNum(cookedG);
    } else if (mode === "published") {
      body.yield_factor = parseNum(factor);
      body.citation = citation.trim() || null;
    } else {
      if (!derived || !cooked) return;
      body.cooked_food_id = cooked.id;
      body.yield_factor = derived.yield_factor;
      body.citation = derived.method_note;
    }
    save.mutate(body);
  }

  const measuredFactor = parseNum(rawG) && parseNum(cookedG) ? parseNum(cookedG)! / parseNum(rawG)! : null;

  return (
    <form className="card stack" onSubmit={submit}>
      <h3>Add a cooking yield</h3>
      <div className="tabs small" role="tablist">
        {(["measured", "published", "derived"] as YieldMode[]).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>
            {m === "measured" ? "I weighed it" : m === "published" ? "Published value" : "Derive from cooked entry"}
          </button>
        ))}
      </div>
      <Field label="Cooking method">
        <input required maxLength={80} value={method} onChange={(e) => setMethod(e.target.value)} placeholder="e.g. roasted, boiled, pan-fried" />
      </Field>
      {mode === "measured" && (
        <div className="grid-2">
          <Field label="Raw weight (g)">
            <input type="number" step="any" min="0" required value={rawG} onChange={(e) => setRawG(e.target.value)} />
          </Field>
          <Field label="Cooked weight (g)" hint={measuredFactor ? `Yield factor ×${fmtNum(measuredFactor, 3)}` : undefined}>
            <input type="number" step="any" min="0" required value={cookedG} onChange={(e) => setCookedG(e.target.value)} />
          </Field>
        </div>
      )}
      {mode === "published" && (
        <div className="grid-2">
          <Field label="Yield factor (cooked ÷ raw)">
            <input type="number" step="any" min="0" max="10" required value={factor} onChange={(e) => setFactor(e.target.value)} placeholder="e.g. 0.75" />
          </Field>
          <Field label="Citation" hint="Required. e.g. USDA Table of Cooking Yields for Meat and Poultry (2014), p. 12">
            <input required value={citation} onChange={(e) => setCitation(e.target.value)} />
          </Field>
        </div>
      )}
      {mode === "derived" && (
        <div className="stack">
          <p className="muted small">
            Pick the cooked version of this food (e.g. the USDA "roasted" entry). The yield is estimated from protein conservation; it's an
            estimate and inherits the weaker trust level of the two entries.
          </p>
          {cooked ? (
            <div className="selected">
              <span>
                {cooked.name} <TrustBadge level={cooked.trust_level} />
              </span>
              <button
                type="button"
                className="btn-link"
                onClick={() => {
                  setCooked(null);
                  setDerived(null);
                }}
              >
                Change
              </button>
            </div>
          ) : (
            <FoodPicker
              excludeId={food.id}
              placeholder="Search for the cooked entry…"
              onPick={(f) => {
                setCooked(f);
                derive.mutate(f);
              }}
            />
          )}
          <ErrorBox error={derive.error} />
          {derived && (
            <div className="alert alert-info">
              Estimated yield <strong>×{fmtNum(derived.yield_factor, 4)}</strong>
              {derived.dry_matter_check !== null && <> (dry-matter cross-check ×{fmtNum(derived.dry_matter_check, 4)})</>}.{" "}
              <TrustBadge level={derived.trust_level} />
              <div className="small muted">{derived.method_note}</div>
            </div>
          )}
        </div>
      )}
      <details>
        <summary>Nutrient retention factors (optional)</summary>
        <p className="muted small">
          Fraction of each nutrient left after cooking (e.g. from the USDA Table of Nutrient Retention Factors). Unlisted nutrients are assumed fully
          retained.
        </p>
        {retention.map((r, i) => (
          <div key={i} className="row">
            <select
              value={r.code}
              onChange={(e) => setRetention(retention.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}
              aria-label="Nutrient"
            >
              <option value="">Nutrient…</option>
              {nutrientDefs.map((n) => (
                <option key={n.code} value={n.code}>
                  {n.name}
                </option>
              ))}
            </select>
            <input
              type="number"
              step="any"
              min="0"
              max="1.5"
              className="w-sm"
              placeholder="0.85"
              value={r.value}
              onChange={(e) => setRetention(retention.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
              aria-label="Retention factor"
            />
            <button type="button" className="btn-link danger" onClick={() => setRetention(retention.filter((_, j) => j !== i))}>
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="btn" onClick={() => setRetention([...retention, { code: "", value: "" }])}>
          + Add factor
        </button>
      </details>
      <Field label="Notes">
        <input maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <ErrorBox error={save.error} />
      <button type="submit" className="btn btn-primary" disabled={save.isPending || (mode === "derived" && !derived)}>
        Save yield
      </button>
    </form>
  );
}

function Yields({ food }: { food: Food }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const yields = useQuery({ queryKey: ["yields", food.id], queryFn: () => api.yields(food.id) });
  const del = useMutation({
    mutationFn: api.deleteYield,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yields", food.id] }),
  });

  return (
    <section className="card stack">
      <h2>Cooking yields</h2>
      <p className="muted small">
        A yield converts raw weight to cooked weight (cooked = raw × factor), so you can weigh food after cooking and still use this raw entry's
        nutrients. Weighing your own batch raw and cooked is the most accurate.
      </p>
      <ErrorBox error={yields.error || del.error} />
      {yields.data?.length === 0 && <p className="muted">No yields yet.</p>}
      <ul className="plain-list">
        {yields.data?.map((y) => (
          <li key={y.id} className="entry">
            <div className="entry-main">
              <div>
                <strong>{y.method}</strong> ×{fmtNum(y.yield_factor, 4)} <span className="chip">{y.basis}</span>
              </div>
              <div className="entry-actions">
                <TrustBadge level={y.trust_level} />
                {(y.owner_id === user?.id || user?.is_admin) && (
                  <button type="button" className="btn-link danger" onClick={() => del.mutate(y.id)}>
                    Delete
                  </button>
                )}
              </div>
            </div>
            {y.citation && <div className="small muted">{y.citation}</div>}
            {y.notes && <div className="small muted">{y.notes}</div>}
            {Object.keys(y.retention).length > 0 && (
              <div className="small muted">Retention factors: {Object.entries(y.retention).map(([k, v]) => `${k} ${v}`).join(", ")}</div>
            )}
            {y.cooked_food_id && (
              <Link className="small" to={`/foods/${y.cooked_food_id}`}>
                Paired cooked entry
              </Link>
            )}
          </li>
        ))}
      </ul>
      {adding ? (
        <AddYield
          food={food}
          onDone={() => {
            setAdding(false);
            qc.invalidateQueries({ queryKey: ["yields", food.id] });
          }}
        />
      ) : (
        <button type="button" className="btn" onClick={() => setAdding(true)}>
          + Add yield
        </button>
      )}
    </section>
  );
}

function FormChoice({ food, row }: { food: Food; row: FormRow }) {
  const qc = useQueryClient();
  const [done, setDone] = useState<number | null>(null);
  const choose = useMutation({
    mutationFn: (key: string | null) => api.setFoodForm(food.id, row.component_name, key),
    onMutate: () => setDone(null),
    onSuccess: (res) => {
      qc.setQueryData(["food-forms", food.id], res.forms);
      setDone(res.recalculated_entries);
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["range"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      qc.invalidateQueries({ queryKey: ["calc"] });
    },
  });
  const name = `form-${food.id}-${row.component_name}`;
  const fromUnit = row.unit ?? "";
  return (
    <fieldset className="fieldset form-choice" disabled={choose.isPending}>
      <legend>
        {row.component_name}: {fmtNum(row.amount)} {fromUnit} → {row.nutrient_name}
      </legend>
      <div className="stack-sm">
        {row.options.map((o) => (
          <label key={o.key} className="option">
            <input type="radio" name={name} checked={row.chosen === o.key} onChange={() => choose.mutate(o.key)} />
            <span className="option-body">
              <span>
                {o.label}{" "}
                <strong className="nowrap">
                  = {fmtNum(o.result)} {o.unit}
                </strong>
              </span>
              <span className="muted small">
                ×{fmtNum(o.factor, 3)} per {fromUnit}
                {o.note ? ` · ${o.note}` : ""} ·{" "}
                <a href={o.source} target="_blank" rel="noopener noreferrer">
                  NIH ODS fact sheet ↗
                </a>
              </span>
            </span>
          </label>
        ))}
        <label className="option">
          <input type="radio" name={name} checked={row.chosen === null} onChange={() => choose.mutate(null)} />
          <span className="option-body">
            <span>Not sure (don't count)</span>
            <span className="muted small">The amount stays listed as uncounted; your totals for {row.nutrient_name} will read low.</span>
          </span>
        </label>
      </div>
      {choose.isPending && <p className="muted small">Saving…</p>}
      {done !== null && (
        <ResultNote ok>
          Recalculated {done} entr{done === 1 ? "y" : "ies"}.
        </ResultNote>
      )}
      <ErrorBox error={choose.error} />
    </fieldset>
  );
}

function FormChoices({ food }: { food: Food }) {
  const forms = useQuery({ queryKey: ["food-forms", food.id], queryFn: () => api.foodForms(food.id) });
  const { hash } = useLocation();
  const ready = !!forms.data?.length;
  useEffect(() => {
    if (ready && hash === "#forms") document.getElementById("forms")?.scrollIntoView({ block: "start" });
  }, [ready, hash]);
  if (forms.error) return <ErrorBox error={forms.error} />;
  if (!forms.data?.length) return null;
  return (
    <section className="card stack" id="forms" aria-labelledby="forms-title">
      <h2 id="forms-title">Choose the form</h2>
      <p className="muted small">
        The label gives these in units that depend on the chemical form. Check the label for the form (e.g. "as retinyl palmitate") and choose
        it; your choice applies to past and future entries.
      </p>
      {forms.data.map((r) => (
        <FormChoice key={r.component_name} food={food} row={r} />
      ))}
    </section>
  );
}

export default function FoodDetailPage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const food = useQuery({ queryKey: ["food", id], queryFn: () => api.food(id) });
  const copy = useMutation({
    mutationFn: () => api.copyFood(id),
    onSuccess: (f) => {
      qc.invalidateQueries({ queryKey: ["foods"] });
      navigate(`/foods/${f.id}/edit`);
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteFood(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["foods"] });
      navigate("/foods");
    },
  });

  if (food.isLoading) return <Loading />;
  if (!food.data) return <ErrorBox error={food.error} />;
  const f = food.data;
  const mine = f.owner_id === user?.id;
  const canDelete = mine || (f.owner_id === null && user?.is_admin);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{f.name}</h1>
          {f.brand && <p className="muted">{f.brand}</p>}
          <div className="row wrap">
            <TrustBadge level={f.trust_level} />
            <span className="chip">{f.kind}</span>
            {f.state && <span className="chip">{f.state}{f.cooking_method ? `, ${f.cooking_method}` : ""}</span>}
            <span className="muted">{basisLabel(f)}</span>
            {f.serving_size_g && <span className="muted">serving {fmtNum(f.serving_size_g)} g</span>}
          </div>
        </div>
        <div className="row wrap">
          <Link className="btn btn-primary" to="/log">
            Log it
          </Link>
          {mine ? (
            <Link className="btn" to={`/foods/${f.id}/edit`}>
              Edit
            </Link>
          ) : (
            <button type="button" className="btn" onClick={() => copy.mutate()} disabled={copy.isPending}>
              Copy to edit
            </button>
          )}
          {canDelete && (
            <button
              type="button"
              className="btn danger"
              onClick={() => {
                if (confirm(`Delete "${f.name}"? Log entries keep their recorded nutrients.`)) del.mutate();
              }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      <ErrorBox error={copy.error || del.error} />

      {f.trust_level === "unverified" && (
        <div className="alert alert-warn">
          <strong>⚠ Unverified data.</strong> {TRUST_INFO.unverified.description}
        </div>
      )}

      <section className="card">
        <h2>Source</h2>
        <dl className="kv">
          <dt>Source</dt>
          <dd>{SOURCE_NAMES[f.source] ?? f.source}</dd>
          {f.source_data_type && (
            <>
              <dt>Data type</dt>
              <dd>{f.source_data_type}</dd>
            </>
          )}
          <dt>Trust</dt>
          <dd>{TRUST_INFO[f.trust_level]?.description}</dd>
          {f.citation && (
            <>
              <dt>Citation</dt>
              <dd>{f.citation}</dd>
            </>
          )}
          {f.source_url && (
            <>
              <dt>Record</dt>
              <dd>
                <a href={f.source_url} target="_blank" rel="noopener noreferrer">
                  View at source ↗
                </a>
              </dd>
            </>
          )}
          {f.fetched_at && (
            <>
              <dt>Fetched</dt>
              <dd>{new Date(f.fetched_at).toLocaleString()}</dd>
            </>
          )}
        </dl>
      </section>

      <section className="card">
        <h2>Nutrients ({basisLabel(f)})</h2>
        <NutrientTable values={f.nutrients} derivations={f.derivations} />
      </section>

      {f.portions.length > 0 && (
        <section className="card">
          <h2>Portions</h2>
          <ul className="plain-list">
            {f.portions.map((p) => (
              <li key={p.id}>
                {p.label} — {fmtNum(p.gram_weight)} g
              </li>
            ))}
          </ul>
        </section>
      )}

      <FormChoices food={f} />

      {f.other_components.length > 0 && (
        <section className="card">
          <ComponentList items={f.other_components} />
        </section>
      )}

      {f.basis === "100g" && f.state !== "cooked" && <Yields food={f} />}
    </div>
  );
}
