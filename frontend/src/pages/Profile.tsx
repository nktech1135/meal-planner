import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, Loading } from "../components/common";
import { browserTimezone, fmtNum, fromLength, fromWeight, lengthUnit, nutrientName, parseNum, toLength, toWeight, useNutrients, weightUnit } from "../lib";
import type { NutrientDef, Profile, TargetBound, UnitSystem } from "../types";
import { Button, rescueFocus, ScrollRegion, useAnnounce, VisuallyHidden } from "../components/a11y";

const CATEGORY_LABELS: Record<string, string> = {
  energy: "Energy",
  macro: "Macronutrients",
  carb: "Carbohydrates",
  lipid: "Fats",
  vitamin: "Vitamins",
  mineral: "Minerals",
  other: "Other",
};
const MAX_PINNED = 40;
/** Always shown on Today anyway. */
const CORE = ["energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g"];

function SearchSources({
  value,
  onChange,
  preferred,
  onPreferred,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  preferred: string | null;
  onPreferred: (v: string | null) => void;
}) {
  const dbs = useQuery({ queryKey: ["food-databases"], queryFn: api.foodDatabases });
  const installed = (dbs.data ?? []).filter((d) => d.records > 0);
  if (installed.length < 2) return null; // nothing to choose between
  return (
    <section className="card stack" id="sources" aria-labelledby="sources-title">
      <h2 id="sources-title">Food databases in search</h2>
      <p className="muted small">Choose which reference databases appear when you search for foods. Your own foods always appear.</p>
      <Field label="Prefer results from" hint="Its foods are listed first when several databases have a match, e.g. your own country's.">
        <select value={preferred ?? "usda_fdc"} onChange={(e) => onPreferred(e.target.value === "usda_fdc" ? null : e.target.value)}>
          {installed.map((d) => (
            <option key={d.source} value={d.source}>
              {d.label} ({d.country})
            </option>
          ))}
        </select>
      </Field>
      <div className="stack-sm">
        {installed.map((d) => (
          <label key={d.source} className="checkbox">
            <input
              type="checkbox"
              checked={!value.includes(d.source)}
              onChange={(e) => onChange(e.target.checked ? value.filter((s) => s !== d.source) : [...value, d.source])}
            />
            <span>
              {d.label} <span className="muted small">· {d.country} · {d.records.toLocaleString()} foods</span>
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

function PinnedNutrients({ defs, value, onChange }: { defs: NutrientDef[]; value: string[]; onChange: (v: string[]) => void }) {
  const categories: string[] = [];
  for (const d of defs) if (!categories.includes(d.category)) categories.push(d.category);
  const full = value.length >= MAX_PINNED;
  return (
    <section className="card stack" id="pinned" aria-labelledby="pinned-title">
      <h2 id="pinned-title">Pinned nutrients</h2>
      <p className="muted small">
        Today shows energy, protein, fat, carbs and fiber plus anything flagged. Pin the nutrients you also want to see every day
        {value.length ? ` (${value.length} pinned)` : ""}.
      </p>
      {categories.map((cat) => (
        <fieldset key={cat} className="fieldset">
          <legend>{CATEGORY_LABELS[cat] ?? cat}</legend>
          <div className="check-grid">
            {defs
              .filter((d) => d.category === cat)
              .map((d) => {
                const checked = value.includes(d.code);
                const core = CORE.includes(d.code);
                return (
                  <label key={d.code} className="checkbox">
                    <input
                      type="checkbox"
                      checked={checked || core}
                      disabled={core || (!checked && full)}
                      onChange={(e) => onChange(e.target.checked ? [...value, d.code] : value.filter((c) => c !== d.code))}
                    />
                    <span>
                      {d.name}
                      {core && <span className="muted small"> (always shown)</span>}
                    </span>
                  </label>
                );
              })}
          </div>
        </fieldset>
      ))}
      {full && <p className="muted small">You can pin up to {MAX_PINNED} nutrients.</p>}
    </section>
  );
}

function timezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  try {
    return intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

/** A metric value converted for display, rounded to one decimal; "" when unset. */
const shown = (v: number | null, convert: (v: number) => number) => (v === null ? "" : String(Math.round(convert(v) * 10) / 10));

type OverrideRow = { code: string; min: string; target: string; max: string };

const toRows = (o: Record<string, TargetBound>): OverrideRow[] =>
  Object.entries(o).map(([code, b]) => ({
    code,
    min: b.min?.toString() ?? "",
    target: b.target?.toString() ?? "",
    max: b.max?.toString() ?? "",
  }));

export default function ProfilePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const { list: nutrientDefs, byCode } = useNutrients();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const targets = useQuery({ queryKey: ["targets"], queryFn: api.targets });
  const [form, setForm] = useState<Profile | null>(null);
  const [overrides, setOverrides] = useState<OverrideRow[]>([]);
  // Height/weight are edited in the chosen units and converted to metric on save.
  // The metric value is kept alongside, so switching units back and forth doesn't drift.
  const [height, setHeight] = useState<{ text: string; cm: number | null }>({ text: "", cm: null });
  const [weight, setWeight] = useState<{ text: string; kg: number | null }>({ text: "", kg: null });
  const tzList = useMemo(timezones, []);
  const browserTz = browserTimezone();

  useEffect(() => {
    if (!profile.data) return;
    // A profile that never had a timezone set gets the browser's zone suggested.
    setForm({ ...profile.data, timezone: profile.data.timezone ?? browserTz, pinned_nutrients: profile.data.pinned_nutrients ?? [] });
    setOverrides(toRows(profile.data.target_overrides ?? {}));
    const u = profile.data.unit_system ?? "metric";
    setHeight({ text: shown(profile.data.height_cm, (v) => toLength(v, u)), cm: profile.data.height_cm });
    setWeight({ text: shown(profile.data.weight_kg, (v) => toWeight(v, u)), kg: profile.data.weight_kg });
  }, [profile.data, browserTz]);

  const { hash } = useLocation();
  const formReady = !!form;
  useEffect(() => {
    if (formReady && hash.length > 1) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [formReady, hash]);

  const announce = useAnnounce();
  const save = useMutation({
    mutationFn: api.saveProfile,
    onSuccess: (p) => {
      announce("Profile saved. Your targets are updated.");
      qc.setQueryData(["profile"], p);
      qc.invalidateQueries({ queryKey: ["targets"] });
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });

  if (profile.isLoading || !form)
    return (
      <div className="stack">
        <h1>Profile</h1>
        {profile.error ? <ErrorBox error={profile.error} /> : <Loading />}
      </div>
    );

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setForm({ ...form, [k]: v });
  const units: UnitSystem = form.unit_system ?? "metric";

  function switchUnits(next: UnitSystem) {
    setHeight({ ...height, text: shown(height.cm, (v) => toLength(v, next)) });
    setWeight({ ...weight, text: shown(weight.kg, (v) => toWeight(v, next)) });
    set("unit_system", next);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const target_overrides: Record<string, TargetBound> = {};
    for (const r of overrides) {
      if (!r.code) continue;
      target_overrides[r.code] = { min: parseNum(r.min), target: parseNum(r.target), max: parseNum(r.max) };
    }
    save.mutate({
      ...form!,
      target_overrides,
      height_cm: height.cm === null ? null : Math.round(height.cm * 10) / 10,
      weight_kg: weight.kg === null ? null : Math.round(weight.kg * 100) / 100,
    });
  }

  return (
    <div className="stack">
      <h1>Profile</h1>
      <p className="muted">
        Signed in as {user?.email}
        {user?.is_admin ? " (admin)" : ""}. These details set your reference intakes and give the advisor context.
      </p>
      <form className="stack" onSubmit={submit}>
        <section className="card stack">
          <div className="grid-3">
            <Field label="Sex (for reference intakes)">
              <select value={form.sex ?? ""} onChange={(e) => set("sex", (e.target.value || null) as Profile["sex"])}>
                <option value="">Not set</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>
            </Field>
            <Field label="Birth date">
              <input type="date" value={form.birth_date ?? ""} onChange={(e) => set("birth_date", e.target.value || null)} />
            </Field>
            <Field label="Life stage">
              <select value={form.life_stage} onChange={(e) => set("life_stage", e.target.value as Profile["life_stage"])}>
                <option value="none">Not pregnant or lactating</option>
                <option value="pregnant">Pregnant</option>
                <option value="lactating">Lactating</option>
              </select>
            </Field>
            <Field label="Units">
              <select value={units} onChange={(e) => switchUnits(e.target.value as UnitSystem)}>
                <option value="metric">Metric (kg, cm)</option>
                <option value="imperial">Imperial (lb, in)</option>
              </select>
            </Field>
            <Field label={`Height (${lengthUnit(units)})`}>
              <input type="number" step="any" min="0" value={height.text}
                onChange={(e) => {
                  const v = parseNum(e.target.value);
                  setHeight({ text: e.target.value, cm: v === null ? null : fromLength(v, units) });
                }} />
            </Field>
            <Field label={`Weight (${weightUnit(units)})`} hint="Updated automatically from your latest weigh-in on Trends.">
              <input type="number" step="any" min="0" value={weight.text}
                onChange={(e) => {
                  const v = parseNum(e.target.value);
                  setWeight({ text: e.target.value, kg: v === null ? null : fromWeight(v, units) });
                }} />
            </Field>
            <Field label="Activity level">
              <select value={form.activity_level} onChange={(e) => set("activity_level", e.target.value as Profile["activity_level"])}>
                <option value="sedentary">Sedentary</option>
                <option value="light">Lightly active</option>
                <option value="moderate">Moderately active</option>
                <option value="active">Active</option>
                <option value="very_active">Very active</option>
              </select>
            </Field>
            <Field label="Goal">
              <select value={form.goal} onChange={(e) => set("goal", e.target.value as Profile["goal"])}>
                <option value="lose">Lose weight</option>
                <option value="maintain">Maintain</option>
                <option value="gain">Gain weight</option>
              </select>
            </Field>
            <Field label="Timezone" hint={form.timezone !== browserTz ? `Your browser reports ${browserTz}.` : "Days start at midnight here."}>
              <input list="tz-list" value={form.timezone ?? ""} onChange={(e) => set("timezone", e.target.value)} required />
              <datalist id="tz-list">
                {tzList.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </Field>
          </div>
          <Field label="Health notes for the advisor" hint="Conditions, medications, allergies, dietary pattern. Only you and the advisor see this.">
            <textarea rows={4} maxLength={4000} value={form.health_notes} onChange={(e) => set("health_notes", e.target.value)} />
          </Field>
        </section>

        <section className="card stack">
          <h2>Target overrides</h2>
          <p className="muted small">Replace a computed target with your own (e.g. from your dietitian). Leave a field blank to clear it.</p>
          {overrides.length > 0 && (
            <div className="row row-head muted small" aria-hidden="true">
              <span className="grow">Nutrient</span>
              <span className="w-sm">Min</span>
              <span className="w-sm">Target</span>
              <span className="w-sm">Max</span>
              <span className="btn-link row-head-spacer">Remove</span>
            </div>
          )}
          {overrides.map((r, i) => {
            const what = r.code ? nutrientName(byCode, r.code) : `override ${i + 1}`;
            return (
              <div key={i} className="row wrap">
                <select
                  className="grow"
                  value={r.code}
                  onChange={(e) => setOverrides(overrides.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}
                  aria-label={`Override ${i + 1}: nutrient`}
                >
                  <option value="">Nutrient…</option>
                  {nutrientDefs.map((n) => (
                    <option key={n.code} value={n.code}>
                      {n.name} ({n.unit})
                    </option>
                  ))}
                </select>
                {(["min", "target", "max"] as const).map((k) => (
                  <input
                    key={k}
                    type="number"
                    step="any"
                    min="0"
                    className="w-sm"
                    placeholder={k}
                    aria-label={`${k === "min" ? "Minimum" : k === "target" ? "Target" : "Maximum"} for ${what}`}
                    value={r[k]}
                    onChange={(e) => setOverrides(overrides.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))}
                  />
                ))}
                <button
                  type="button"
                  className="btn-link danger"
                  onClick={() => {
                    setOverrides(overrides.filter((_, j) => j !== i));
                    rescueFocus(() => document.getElementById("add-override"));
                  }}
                >
                  Remove<VisuallyHidden> {what}</VisuallyHidden>
                </button>
              </div>
            );
          })}
          <button id="add-override" type="button" className="btn" onClick={() => setOverrides([...overrides, { code: "", min: "", target: "", max: "" }])}>
            <span aria-hidden="true">+</span> Add override
          </button>
        </section>

        <PinnedNutrients defs={nutrientDefs} value={form.pinned_nutrients} onChange={(v) => set("pinned_nutrients", v)} />
        <SearchSources
          value={form.hidden_sources ?? []}
          onChange={(v) => set("hidden_sources", v)}
          preferred={form.preferred_source ?? null}
          onPreferred={(v) => set("preferred_source", v)}
        />

        <ErrorBox error={save.error} />
        <div className="row">
          <Button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save profile"}
          </Button>
          {save.isSuccess && <span className="muted small">Saved.</span>}
        </div>
      </form>

      <section className="card stack">
        <h2>Your daily targets</h2>
        <ErrorBox error={targets.error} />
        {targets.data?.warnings.map((w, i) => (
          <div key={i} className="alert alert-warn">
            {w}
          </div>
        ))}
        {targets.data && Object.keys(targets.data.targets).length > 0 && (
          <ScrollRegion label="Your daily targets">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nutrient</th>
                  <th scope="col" className="num">
                    Min
                  </th>
                  <th scope="col" className="num">
                    Target
                  </th>
                  <th scope="col" className="num">
                    Upper limit
                  </th>
                  <th scope="col">Basis</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(targets.data.targets)
                  .sort(([a], [b]) => nutrientDefs.findIndex((n) => n.code === a) - nutrientDefs.findIndex((n) => n.code === b))
                  .map(([code, t]) => (
                    <tr key={code}>
                      <th scope="row" className="th-plain">
                        {nutrientName(byCode, code)} <span className="muted small">{byCode[code]?.unit}</span>
                      </th>
                      <td className="num">{fmtNum(t.min)}</td>
                      <td className="num">{fmtNum(t.target)}</td>
                      <td className="num">
                        {fmtNum(t.max)}
                        {t.ul_scope === "supplemental" && <span className="muted small"> supplements only</span>}
                      </td>
                      <td className="small">
                        <span title={t.source}>{t.kind}</span>
                        {t.note && <div className="muted">{t.note}</div>}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
        <p className="muted small">
          Reference intakes are the National Academies DRIs for adults (via NIH ODS tables). Energy is an estimate (Mifflin-St Jeor × activity);
          adjust it with your weight trend.
        </p>
      </section>
    </div>
  );
}
