import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { DailyBars, WeightChart, type RefLine } from "../components/charts";
import { ErrorBox, Field, Loading, ResultNote, StatusPill } from "../components/common";
import {
  fmt1,
  fmtAmount,
  fmtNum,
  fmtShortDate,
  fromLength,
  fromWeight,
  invalidateAfterWeighIn,
  lengthUnit,
  nutrientName,
  parseNum,
  todayISO,
  toLength,
  toWeight,
  useNutrients,
  weightUnit,
} from "../lib";
import type { BodyMeasurement, NutrientDef, Profile, TrendEvaluation, Trends, UnitSystem } from "../types";
import { Button, focusSoon, rescueFocus, useAnnounce } from "../components/a11y";

const PERIODS = [7, 30, 90];
const GROUPS: { title: string; categories: string[] }[] = [
  { title: "Energy & macronutrients", categories: ["energy", "macro", "carb", "lipid"] },
  { title: "Vitamins", categories: ["vitamin"] },
  { title: "Minerals", categories: ["mineral"] },
  { title: "Other", categories: ["other"] },
];
const GOAL_FACTOR: Record<Profile["goal"], number> = { lose: 0.85, maintain: 1, gain: 1.1 };
const GOAL_TEXT: Record<Profile["goal"], string> = { lose: "× 0.85 for your weight-loss goal", maintain: "for your maintain goal", gain: "× 1.10 for your weight-gain goal" };

/** Reference lines for a nutrient's evaluation row (equal values merged; supplement-only limits left out). */
function refsFor(row: TrendEvaluation | undefined): RefLine[] {
  if (!row) return [];
  const out: RefLine[] = [];
  if (row.target !== null) out.push({ kind: "target", value: row.target, label: `target ${fmtNum(row.target)}` });
  if (row.min !== null && row.min !== row.target) out.push({ kind: "min", value: row.min, label: `min ${fmtNum(row.min)}` });
  if (row.max !== null && row.ul_scope !== "supplemental") {
    out.push(row.max_is_limit === false
      ? { kind: "range", value: row.max, label: `range top ${fmtNum(row.max)}` }
      : { kind: "max", value: row.max, label: `limit ${fmtNum(row.max)}` });
  }
  return out;
}

function NutrientChart({ t, code, def }: { t: Trends; code: string; def?: NutrientDef }) {
  const row = t.evaluation.find((r) => r.code === code);
  const unit = def?.unit ?? "";
  return (
    <>
      <DailyBars
        days={t.daily.map((d) => ({ date: d.date, value: d.logged ? (d.totals[code] ?? 0) : null }))}
        refs={refsFor(row)}
        unit={unit}
        label={def?.name ?? code}
        format={(v) => fmtNum(v)}
      />
      {row?.max !== null && row?.ul_scope === "supplemental" && (
        <p className="muted small">The upper limit ({fmtAmount(row.max, unit)}) applies to supplements only, so it isn't drawn against total intake.</p>
      )}
    </>
  );
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className="card stack-sm chart-card" aria-labelledby={id}>
      <div>
        <h2 className="h-card" id={id}>
          {title}
        </h2>
        {subtitle && <p className="muted small chart-sub">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function AveragesTable({ t }: { t: Trends }) {
  const { byCode, list } = useNutrients();
  const order = (c: string) => {
    const i = list.findIndex((n) => n.code === c);
    return i === -1 ? 999 : i;
  };
  if (!t.evaluation.length) return null;
  return (
    <section className="card stack-sm" aria-labelledby="avg-title">
      <h2 id="avg-title">Averages against your targets</h2>
      <p className="small">
        <strong>Judged on averages, not single days.</strong> Most vitamins and minerals only matter over time, so a low day is normal; a low{" "}
        <em>average</em> is worth acting on. Averages use the {t.logged_days} logged day{t.logged_days === 1 ? "" : "s"} only.
      </p>
      {t.logged_days === 0 ? (
        <p className="muted">Nothing logged in this period.</p>
      ) : (
        GROUPS.map((g) => {
          const rows = t.evaluation
            .filter((r) => g.categories.includes(byCode[r.code]?.category ?? "other"))
            .sort((a, b) => order(a.code) - order(b.code));
          if (!rows.length) return null;
          return (
            <div key={g.title} className="table-wrap">
              <table className="table avg-table">
                <caption className="h-sm">{g.title}</caption>
                <thead>
                  <tr>
                    <th scope="col">Nutrient</th>
                    <th scope="col" className="num">
                      Average
                    </th>
                    <th scope="col">Status</th>
                    <th scope="col" className="num">
                      On target
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const unit = byCode[r.code]?.unit ?? "";
                    const limits = [
                      r.min !== null && `min ${fmtNum(r.min)}`,
                      r.target !== null && `target ${fmtNum(r.target)}`,
                      r.max !== null && `limit ${fmtNum(r.max)}${r.ul_scope === "supplemental" ? " (supplements)" : ""}`,
                    ].filter(Boolean);
                    return (
                      <tr key={r.code} className={r.status === "above_max" ? "row-alert" : ""}>
                        <th scope="row">
                          <span className="avg-name">{nutrientName(byCode, r.code)}</span>
                          <span className="muted small avg-limits">
                            {limits.join(" · ")} {unit}
                          </span>
                        </th>
                        <td className="num">
                          {fmtNum(r.amount)} <span className="muted small">{unit}</span>
                          {r.ul_scope === "supplemental" && r.max !== null && (
                            <span className="muted small avg-limits">supplements {fmtNum(r.limit_amount)}</span>
                          )}
                        </td>
                        <td>
                          <StatusPill status={r.status} />
                        </td>
                        <td className="num">
                          {r.days_ok}{" "}
                          <span className="muted small">
                            of {t.logged_days}
                            <span className="avg-phone-only"> days on target</span>
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        })
      )}
    </section>
  );
}

function EnergyEstimateCard({ t, units }: { t: Trends; units: UnitSystem }) {
  const qc = useQueryClient();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const e = t.energy_estimate;
  const goal = profile.data?.goal ?? "maintain";
  const suggested = e.maintenance_kcal !== undefined ? Math.round((e.maintenance_kcal * GOAL_FACTOR[goal]) / 10) * 10 : null;
  const current = profile.data?.target_overrides?.energy_kcal?.target ?? null;
  const save = useMutation({
    mutationFn: () => {
      const p = profile.data!;
      return api.saveProfile({ ...p, target_overrides: { ...p.target_overrides, energy_kcal: { min: null, target: suggested, max: null } } });
    },
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      qc.invalidateQueries({ queryKey: ["targets"] });
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
  const change = e.trend_change_kg ?? 0;
  return (
    <section className="card stack-sm" aria-labelledby="estimate-title">
      <h2 id="estimate-title">Your energy needs, from your own data</h2>
      {!e.available ? (
        <>
          <p className="alert alert-info small">
            <strong>Not enough data yet.</strong> {e.reason}
          </p>
          <p className="muted small">{e.method}</p>
        </>
      ) : (
        <>
          <div className="stat-row">
            <div className="stat stat-hero">
              <span className="stat-label">Estimated maintenance</span>
              <span className="stat-value">{e.maintenance_kcal!.toLocaleString()} kcal</span>
            </div>
            <div className="stat">
              <span className="stat-label">Average intake</span>
              <span className="stat-value">{e.average_intake_kcal!.toLocaleString()} kcal</span>
            </div>
            <div className="stat">
              <span className="stat-label">Trend change</span>
              <span className="stat-value">
                {change > 0 ? "+" : change < 0 ? "−" : ""}
                {fmt1(Math.abs(toWeight(change, units)))} {weightUnit(units)}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Over</span>
              <span className="stat-value">{e.days} days</span>
            </div>
            <div className="stat">
              <span className="stat-label">Days logged</span>
              <span className="stat-value">{Math.round((e.logged_fraction ?? 0) * 100)}%</span>
            </div>
          </div>
          <p className="muted small">
            {e.method} It's an estimate: missed or under-logged food makes it read low.
          </p>
          {suggested !== null && (
            <div className="stack-sm">
              <p className="small">
                Suggested energy target: <strong>{suggested.toLocaleString()} kcal</strong> (maintenance {GOAL_TEXT[goal]}).
                {current !== null && <> Your current override is {fmtNum(current)} kcal.</>}
              </p>
              <div>
                <Button type="button" className="btn btn-primary" disabled={!profile.data || save.isPending || current === suggested} onClick={() => save.mutate()}>
                  {save.isPending ? "Saving…" : current === suggested ? "This is your energy target" : "Use as my energy target"}
                </Button>
              </div>
              {save.isSuccess && (
                <ResultNote ok>
                  Energy target set to {suggested.toLocaleString()} kcal. Change it any time under <Link to="/profile">Profile → Target overrides</Link>.
                </ResultNote>
              )}
              <ErrorBox error={save.error || profile.error} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

const numOrEmpty = (v: number | null, convert: (v: number) => number) => (v === null ? "" : String(Math.round(convert(v) * 10) / 10));

function BodyForm({ units, editing, onDone }: { units: UnitSystem; editing: BodyMeasurement | null; onDone: () => void }) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const [date, setDate] = useState(todayISO());
  const [weight, setWeight] = useState("");
  const [fat, setFat] = useState("");
  const [waist, setWaist] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!editing) return;
    setDate(editing.date);
    setWeight(numOrEmpty(editing.weight_kg, (v) => toWeight(v, units)));
    setFat(editing.body_fat_pct === null ? "" : String(editing.body_fat_pct));
    setWaist(numOrEmpty(editing.waist_cm, (v) => toLength(v, units)));
    setNote(editing.note);
  }, [editing, units]);
  const w = parseNum(weight);
  const f = parseNum(fat);
  const wa = parseNum(waist);
  const save = useMutation({
    mutationFn: () =>
      api.putBody(date, {
        weight_kg: w === null ? null : Math.round(fromWeight(w, units) * 100) / 100,
        body_fat_pct: f,
        waist_cm: wa === null ? null : Math.round(fromLength(wa, units) * 10) / 10,
        note: note.trim(),
      }),
    onSuccess: () => {
      invalidateAfterWeighIn(qc);
      announce(`Saved measurements for ${fmtShortDate(date)}.`);
      setWeight("");
      setFat("");
      setWaist("");
      setNote("");
      setDate(todayISO());
      onDone();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (w !== null || f !== null || wa !== null) save.mutate();
  }
  return (
    <form className="stack-sm" onSubmit={submit} aria-label={editing ? `Edit measurements for ${fmtShortDate(editing.date)}` : "Add measurements"}>
      <div className="grid-4">
        <Field label="Date">
          <input id="body-date" type="date" required value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={`Weight (${weightUnit(units)})`}>
          <input type="number" inputMode="decimal" step="any" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} />
        </Field>
        <Field label="Body fat (%)">
          <input type="number" inputMode="decimal" step="any" min="1" max="75" value={fat} onChange={(e) => setFat(e.target.value)} />
        </Field>
        <Field label={`Waist (${lengthUnit(units)})`}>
          <input type="number" inputMode="decimal" step="any" min="0" value={waist} onChange={(e) => setWaist(e.target.value)} />
        </Field>
      </div>
      <Field label="Note (optional)">
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <ErrorBox error={save.error} />
      <div className="row wrap">
        <Button type="submit" className="btn btn-primary" disabled={save.isPending || (w === null && f === null && wa === null)}>
          {save.isPending ? "Saving…" : editing ? "Save changes" : "Save measurements"}
        </Button>
        {editing && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              onDone();
              rescueFocus(() => document.getElementById("body-date"));
            }}
          >
            Cancel
          </button>
        )}
      </div>
      <p className="muted small">One entry per day; saving a date that already has one updates it. Your profile weight follows the latest weigh-in.</p>
    </form>
  );
}

function BodySection({ units }: { units: UnitSystem }) {
  const qc = useQueryClient();
  // The whole history (one row a day at most), not just the server's default of the last 90 days.
  const body = useQuery({ queryKey: ["body", "all"], queryFn: () => api.body("1900-01-01") });
  const [editing, setEditing] = useState<BodyMeasurement | null>(null);
  const [showAll, setShowAll] = useState(false);
  const announce = useAnnounce();
  const del = useMutation({
    mutationFn: api.deleteBody,
    onSuccess: (_, date) => {
      invalidateAfterWeighIn(qc);
      announce(`Deleted the measurements for ${fmtShortDate(date)}.`);
      rescueFocus(() => listHeading.current);
    },
  });
  const rows = [...(body.data ?? [])].reverse();
  const shown = showAll ? rows : rows.slice(0, 10);
  const listHeading = useRef<HTMLHeadingElement>(null);
  return (
    <section className="card stack" aria-labelledby="body-title">
      <h2 id="body-title">Body measurements</h2>
      <BodyForm units={units} editing={editing} onDone={() => setEditing(null)} />
      <ErrorBox error={body.error || del.error} />
      {body.isLoading && <Loading />}
      {rows.length > 0 && (
        <div className="stack-sm">
          <h3 className="h-sm" ref={listHeading}>
            Last 90 days
          </h3>
          <ul className="plain-list body-list">
            {shown.map((m) => (
              <li key={m.date} className="entry">
                <div className="entry-main">
                  <div className="entry-text">
                    <strong>{fmtShortDate(m.date)}</strong>{" "}
                    <span className="muted">
                      {[
                        m.weight_kg !== null && `${fmt1(toWeight(m.weight_kg, units))} ${weightUnit(units)}`,
                        m.body_fat_pct !== null && `${fmt1(m.body_fat_pct)}% fat`,
                        m.waist_cm !== null && `waist ${fmt1(toLength(m.waist_cm, units))} ${lengthUnit(units)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    {m.note && <div className="muted small">{m.note}</div>}
                  </div>
                  <div className="entry-actions">
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => {
                        setEditing(m);
                        // The form is above the list: take focus there, ready to change the values.
                        focusSoon(() => document.getElementById("body-date"));
                      }}
                      aria-label={`Edit measurements for ${fmtShortDate(m.date)}`}
                    >
                      Edit
                    </button>
                    <Button
                      type="button"
                      className="btn-link danger"
                      disabled={del.isPending}
                      onClick={() => {
                        if (confirm(`Delete the measurements for ${fmtShortDate(m.date)}?`)) del.mutate(m.date);
                      }}
                      aria-label={`Delete measurements for ${fmtShortDate(m.date)}`}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {rows.length > 10 && (
            <div>
              <button type="button" className="btn-link" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>
                {showAll ? "Show fewer" : `Show all ${rows.length}`}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function TrendsPage() {
  const [params, setParams] = useSearchParams();
  const days = PERIODS.includes(Number(params.get("days"))) ? Number(params.get("days")) : 30;
  const { list, byCode } = useNutrients();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const units: UnitSystem = profile.data?.unit_system ?? "metric";
  const trends = useQuery({ queryKey: ["trends", days], queryFn: () => api.trends(days), placeholderData: (prev) => prev });
  const t = trends.data;
  const withTarget = new Set(t?.evaluation.map((r) => r.code));
  const nutrient = params.get("n") && byCode[params.get("n")!] ? params.get("n")! : "fiber_g";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    next.set(k, v);
    setParams(next, { replace: true });
  };

  const energy = t?.evaluation.find((r) => r.code === "energy_kcal");
  const protein = t?.evaluation.find((r) => r.code === "protein_g");
  const stale = trends.isPlaceholderData && trends.isFetching;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Trends</h1>
        <div className="seg" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={days === p} className={days === p ? "active" : ""} onClick={() => set("days", String(p))}>
              {p} days
            </button>
          ))}
        </div>
      </div>
      <ErrorBox error={trends.error} />
      {trends.isLoading && <Loading />}
      {t && (
        <div className={`stack ${stale ? "is-stale" : ""}`} aria-busy={stale}>
          <section className="card summary-line">
            <p className="summary-big">
              Logged <strong>{t.logged_days}</strong> of {t.days} days
            </p>
            <p className="muted small">
              {fmtShortDate(t.start)} – {fmtShortDate(t.end)}. Days with nothing logged are left out of averages, so they don't drag them down.
            </p>
          </section>
          {t.warnings.map((w, i) => (
            <div key={i} className="alert alert-warn">
              {w} {w.includes("profile") && <Link to="/profile">Open profile</Link>}
            </div>
          ))}

          <div className="chart-grid">
            <ChartCard
              title="Energy"
              subtitle={`kcal per day${energy?.target ? ` vs your target of ${fmtNum(energy.target)} kcal` : ""}${t.averages.energy_kcal !== undefined ? ` · average ${fmtNum(t.averages.energy_kcal)} kcal` : ""}`}
            >
              <NutrientChart t={t} code="energy_kcal" def={byCode.energy_kcal} />
            </ChartCard>
            <ChartCard
              title="Protein"
              subtitle={`grams per day${protein?.min ? ` vs your minimum of ${fmtNum(protein.min)} g` : ""}${t.averages.protein_g !== undefined ? ` · average ${fmtNum(t.averages.protein_g)} g` : ""}`}
            >
              <NutrientChart t={t} code="protein_g" def={byCode.protein_g} />
            </ChartCard>
          </div>

          <ChartCard title="Weight" subtitle={`${weightUnit(units)} · the trend smooths out day-to-day water swings`}>
            {t.weight.length === 0 ? (
              <p className="muted small">No weigh-ins in this period. Add one below.</p>
            ) : (
              <WeightChart
                dates={t.daily.map((d) => d.date)}
                points={t.weight.map((w) => ({ date: w.date, reading: toWeight(w.weight_kg, units), trend: toWeight(w.trend_kg, units) }))}
                unit={weightUnit(units)}
                format={fmt1}
              />
            )}
          </ChartCard>

          <section className="card stack-sm chart-card" aria-labelledby="any-title">
            <div className="row between wrap align-end">
              <h2 id="any-title" className="h-card">
                Any nutrient
              </h2>
              <Field label="Nutrient">
                <select value={nutrient} onChange={(e) => set("n", e.target.value)}>
                  <optgroup label="With a target">
                    {list
                      .filter((n) => withTarget.has(n.code))
                      .map((n) => (
                        <option key={n.code} value={n.code}>
                          {n.name}
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="Other">
                    {list
                      .filter((n) => !withTarget.has(n.code))
                      .map((n) => (
                        <option key={n.code} value={n.code}>
                          {n.name}
                        </option>
                      ))}
                  </optgroup>
                </select>
              </Field>
            </div>
            <p className="muted small chart-sub">
              {byCode[nutrient]?.unit} per day
              {t.averages[nutrient] !== undefined && ` · average ${fmtAmount(t.averages[nutrient], byCode[nutrient]?.unit)}`}
              {!withTarget.has(nutrient) && " · no target for this nutrient"}
            </p>
            <NutrientChart t={t} code={nutrient} def={byCode[nutrient]} />
          </section>

          <AveragesTable t={t} />
          <EnergyEstimateCard t={t} units={units} />
        </div>
      )}
      <BodySection units={units} />
    </div>
  );
}
