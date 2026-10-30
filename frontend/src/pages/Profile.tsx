import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, Loading } from "../components/common";
import { browserTimezone, fmtNum, nutrientName, parseNum, useNutrients } from "../lib";
import type { Profile, TargetBound } from "../types";

function timezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  try {
    return intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

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
  const tzList = useMemo(timezones, []);
  const browserTz = browserTimezone();

  useEffect(() => {
    if (!profile.data) return;
    // A profile that never had a timezone set gets the browser's zone suggested.
    setForm({ ...profile.data, timezone: profile.data.timezone ?? browserTz });
    setOverrides(toRows(profile.data.target_overrides ?? {}));
  }, [profile.data, browserTz]);

  const save = useMutation({
    mutationFn: api.saveProfile,
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      qc.invalidateQueries({ queryKey: ["targets"] });
      qc.invalidateQueries({ queryKey: ["day"] });
    },
  });

  if (profile.isLoading || !form) return profile.error ? <ErrorBox error={profile.error} /> : <Loading />;

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setForm({ ...form, [k]: v });

  function submit(e: FormEvent) {
    e.preventDefault();
    const target_overrides: Record<string, TargetBound> = {};
    for (const r of overrides) {
      if (!r.code) continue;
      target_overrides[r.code] = { min: parseNum(r.min), target: parseNum(r.target), max: parseNum(r.max) };
    }
    save.mutate({ ...form!, target_overrides });
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
            <Field label="Height (cm)">
              <input type="number" step="any" min="0" value={form.height_cm ?? ""} onChange={(e) => set("height_cm", parseNum(e.target.value))} />
            </Field>
            <Field label="Weight (kg)">
              <input type="number" step="any" min="0" value={form.weight_kg ?? ""} onChange={(e) => set("weight_kg", parseNum(e.target.value))} />
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
          {overrides.map((r, i) => (
            <div key={i} className="row wrap">
              <select
                value={r.code}
                onChange={(e) => setOverrides(overrides.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}
                aria-label="Nutrient"
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
                  aria-label={k}
                  value={r[k]}
                  onChange={(e) => setOverrides(overrides.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))}
                />
              ))}
              <button type="button" className="btn-link danger" onClick={() => setOverrides(overrides.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          <button type="button" className="btn" onClick={() => setOverrides([...overrides, { code: "", min: "", target: "", max: "" }])}>
            + Add override
          </button>
        </section>

        <ErrorBox error={save.error} />
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save profile"}
          </button>
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
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Nutrient</th>
                  <th className="num">Min</th>
                  <th className="num">Target</th>
                  <th className="num">Upper limit</th>
                  <th>Basis</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(targets.data.targets)
                  .sort(([a], [b]) => nutrientDefs.findIndex((n) => n.code === a) - nutrientDefs.findIndex((n) => n.code === b))
                  .map(([code, t]) => (
                    <tr key={code}>
                      <td>
                        {nutrientName(byCode, code)} <span className="muted small">{byCode[code]?.unit}</span>
                      </td>
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
          </div>
        )}
        <p className="muted small">
          Reference intakes are the National Academies DRIs for adults (via NIH ODS tables). Energy is an estimate (Mifflin-St Jeor × activity);
          adjust it with your weight trend.
        </p>
      </section>
    </div>
  );
}
