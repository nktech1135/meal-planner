import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ComponentList, ErrorBox, Loading, MacroLine, Notes } from "../components/common";
import { TrustBadge, TrustLegend, TRUST_INFO } from "../components/TrustBadge";
import { fmtAmount, fmtNum, localDateISO, nutrientName, useNutrients } from "../lib";
import { MEALS, type Evaluation, type LogEntry, type NutrientDef, type Trust } from "../types";

const GROUPS: { title: string; categories: string[] }[] = [
  { title: "Energy & macronutrients", categories: ["energy", "macro", "carb", "lipid"] },
  { title: "Vitamins", categories: ["vitamin"] },
  { title: "Minerals", categories: ["mineral"] },
  { title: "Other", categories: ["other"] },
];

function TargetRow({ row, def }: { row: Evaluation; def?: NutrientDef }) {
  const unit = def?.unit ?? "";
  const scale = Math.max(row.amount, row.limit_amount, row.target ?? 0, row.min ?? 0, row.max ?? 0) * 1.08 || 1;
  const pct = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  const statusText = row.status === "above_max" ? "Above limit" : row.status === "below" ? "Below" : "OK";
  const supplementalUL = row.ul_scope === "supplemental" && row.max !== null;
  return (
    <div className={`target-row status-${row.status}`}>
      <div className="target-head">
        <span className="target-name">{def?.name ?? row.code}</span>
        <span className="target-amount">
          {fmtAmount(row.amount, unit)}
          <span className={`status-pill status-${row.status}`}>
            {row.status === "above_max" ? "⚠ " : ""}
            {statusText}
          </span>
        </span>
      </div>
      <div className="bar" aria-hidden="true">
        <div className="bar-fill" style={{ width: pct(row.amount) }} />
        {supplementalUL && <div className="bar-fill bar-fill-supp" style={{ width: pct(row.limit_amount) }} />}
        {row.min !== null && <div className="tick tick-min" style={{ left: pct(row.min) }} />}
        {row.target !== null && <div className="tick tick-target" style={{ left: pct(row.target) }} />}
        {row.max !== null && <div className="tick tick-max" style={{ left: pct(row.max) }} />}
      </div>
      <div className="target-meta muted small">
        {row.min !== null && <span>min {fmtNum(row.min)}</span>}
        {row.target !== null && <span>target {fmtNum(row.target)}</span>}
        {row.max !== null && (
          <span>
            {row.kind === "limit" || row.kind === "AI/CDRR" ? "limit" : "upper limit"} {fmtNum(row.max)}
            {supplementalUL && ` (supplements only: ${fmtAmount(row.limit_amount, unit)})`}
          </span>
        )}
        <span title={row.source}>{row.kind}</span>
      </div>
      {row.note && <div className="muted small">{row.note}</div>}
    </div>
  );
}

function EnergyByTrust({ data }: { data: Partial<Record<Trust, number>> }) {
  const entries = Object.entries(data) as [Trust, number][];
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) return null;
  return (
    <section className="card">
      <h2>Where today's energy data came from</h2>
      <div className="stacked" aria-hidden="true">
        {entries.map(([t, v]) => (
          <div key={t} className={`stacked-seg seg-${t}`} style={{ width: `${(v / total) * 100}%` }} />
        ))}
      </div>
      <ul className="plain-list trust-breakdown">
        {entries.map(([t, v]) => (
          <li key={t}>
            <TrustBadge level={t} /> {Math.round(v)} kcal ({Math.round((v / total) * 100)}%)
            {t === "unverified" && <span className="warn-text"> — {TRUST_INFO.unverified.description}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function EntryItem({ e, onDelete, deleting }: { e: LogEntry; onDelete: () => void; deleting: boolean }) {
  const time = new Date(e.consumed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const unit = e.unit.startsWith("portion:") ? "portion" : e.unit;
  return (
    <li className={`entry ${e.trust_level === "unverified" ? "entry-unverified" : ""}`}>
      <div className="entry-main">
        <div>
          <strong>{e.label}</strong>{" "}
          <span className="muted">
            {fmtNum(e.quantity)} {unit}
            {e.weighed_state === "cooked" ? " (weighed cooked)" : ""}
            {e.grams ? ` · ${fmtNum(e.grams)} g` : ""} · {time}
          </span>
        </div>
        <div className="entry-actions">
          <TrustBadge level={e.trust_level} />
          <button type="button" className="btn-link danger" onClick={onDelete} disabled={deleting} aria-label={`Delete ${e.label}`}>
            Delete
          </button>
        </div>
      </div>
      <MacroLine values={e.nutrients} />
      <Notes notes={e.calc_notes} />
      {e.note && <div className="muted small">Note: {e.note}</div>}
    </li>
  );
}

export default function TodayPage() {
  const [day, setDay] = useState<string | null>(null);
  const qc = useQueryClient();
  const { byCode } = useNutrients();
  const summary = useQuery({ queryKey: ["day", day], queryFn: () => api.day(day ?? undefined) });
  const del = useMutation({
    mutationFn: api.deleteLog,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["day"] }),
  });

  const s = summary.data;
  const shownDay = day ?? s?.date ?? "";

  function shift(days: number) {
    if (!shownDay) return;
    const d = new Date(`${shownDay}T12:00:00`);
    d.setDate(d.getDate() + days);
    setDay(localDateISO(d));
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Today</h1>
        <div className="row">
          <button type="button" className="btn" onClick={() => shift(-1)} aria-label="Previous day">
            ‹
          </button>
          <input type="date" value={shownDay} onChange={(e) => setDay(e.target.value || null)} aria-label="Day" />
          <button type="button" className="btn" onClick={() => shift(1)} aria-label="Next day">
            ›
          </button>
          <Link to="/log" className="btn btn-primary">
            + Add entry
          </Link>
        </div>
      </div>

      <ErrorBox error={summary.error || del.error} />
      {summary.isLoading && <Loading />}

      {s && (
        <>
          {s.alerts.length > 0 && (
            <div className="alert alert-danger" role="alert">
              <strong>⚠ Upper limit exceeded</strong>
              <ul>
                {s.alerts.map((a, i) => (
                  <li key={i}>{a.replace(/^(\w+):/, (_, code: string) => `${nutrientName(byCode, code)}:`)}</li>
                ))}
              </ul>
            </div>
          )}
          {s.warnings.map((w, i) => (
            <div key={i} className="alert alert-warn">
              {w} {w.includes("profile") && <Link to="/profile">Open profile</Link>}
            </div>
          ))}

          <section className="card">
            <h2>Totals</h2>
            <MacroLine values={s.totals} />
          </section>

          <section className="card">
            <h2>Log</h2>
            {s.entries.length === 0 && <p className="muted">Nothing logged for this day.</p>}
            {MEALS.map((meal) => {
              const items = s.entries.filter((e) => e.meal === meal);
              if (!items.length) return null;
              const kcal = items.reduce((sum, e) => sum + (e.nutrients.energy_kcal ?? 0), 0);
              return (
                <div key={meal} className="meal-group">
                  <h3>
                    {meal[0].toUpperCase() + meal.slice(1)} <span className="muted small">{Math.round(kcal)} kcal</span>
                  </h3>
                  <ul className="plain-list">
                    {items.map((e) => (
                      <EntryItem key={e.id} e={e} onDelete={() => del.mutate(e.id)} deleting={del.isPending} />
                    ))}
                  </ul>
                </div>
              );
            })}
          </section>

          <EnergyByTrust data={s.energy_by_trust} />

          {s.evaluation.length > 0 && (
            <section className="card">
              <h2>Against your targets</h2>
              <p className="muted small">
                Ticks mark <span className="key key-min">min</span> <span className="key key-target">target</span>{" "}
                <span className="key key-max">upper limit</span>. Where an upper limit applies only to supplements, the darker bar shows supplement
                intake.
              </p>
              {GROUPS.map((g) => {
                const rows = s.evaluation.filter((r) => g.categories.includes(byCode[r.code]?.category ?? "other"));
                if (!rows.length) return null;
                return (
                  <div key={g.title} className="target-group">
                    <h3>{g.title}</h3>
                    {rows.map((r) => (
                      <TargetRow key={r.code} row={r} def={byCode[r.code]} />
                    ))}
                  </div>
                );
              })}
            </section>
          )}

          {s.other_components.length > 0 && (
            <section className="card">
              <ComponentList items={s.other_components} title="Other supplement components (not in the nutrient catalog)" />
            </section>
          )}
          <TrustLegend />
        </>
      )}
    </div>
  );
}
