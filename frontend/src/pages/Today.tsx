import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { ComponentList, ErrorBox, Field, Loading, MacroLine, Notes } from "../components/common";
import { EntryEditor } from "../components/EntryEditor";
import { TrustBadge, TrustLegend, TRUST_INFO } from "../components/TrustBadge";
import { addDays, fmtAmount, fmtDay, fmtNum, mealLabel, nutrientName, readPref, todayISO, unitText, useNutrients, writePref } from "../lib";
import { MEALS, type DaySummary, type Evaluation, type LogEntry, type Meal, type NutrientDef, type Trust } from "../types";

const GROUPS: { title: string; categories: string[] }[] = [
  { title: "Energy & macronutrients", categories: ["energy", "macro", "carb", "lipid"] },
  { title: "Vitamins", categories: ["vitamin"] },
  { title: "Minerals", categories: ["mineral"] },
  { title: "Other", categories: ["other"] },
];

/** Always shown in the condensed view. */
const CORE = ["energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g"];
const SHOW_ALL_PREF = "today.showAllNutrients";

/** Worth showing even when collapsed: over a limit, well under target, or only partly counted. */
function isFlagged(r: Evaluation): boolean {
  if (r.status === "above_max" || r.status === "partial") return true;
  const goal = r.target ?? r.min;
  return r.status === "below" && goal !== null && goal > 0 && r.amount < goal * 0.5;
}

const STATUS: Record<Evaluation["status"], { text: string; icon: string }> = {
  ok: { text: "OK", icon: "" },
  below: { text: "Below", icon: "" },
  above_max: { text: "Above limit", icon: "⚠ " },
  partial: { text: "Partly counted", icon: "◐ " },
};

function TargetRow({ row, def }: { row: Evaluation; def?: NutrientDef }) {
  const unit = def?.unit ?? "";
  const scale = Math.max(row.amount, row.limit_amount, row.target ?? 0, row.min ?? 0, row.max ?? 0) * 1.08 || 1;
  const pct = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  const supplementalUL = row.ul_scope === "supplemental" && row.max !== null;
  const status = STATUS[row.status] ?? STATUS.ok;
  return (
    <div className={`target-row status-${row.status}`}>
      <div className="target-head">
        <span className="target-name">{def?.name ?? row.code}</span>
        <span className="target-amount">
          {fmtAmount(row.amount, unit)}
          <span className={`status-pill status-${row.status}`}>
            {status.icon}
            {status.text}
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
      {row.uncounted?.length > 0 && (
        <ul className="plain-list uncounted small">
          {row.uncounted.map((u, i) => (
            <li key={`${u.entry_id}-${i}`}>
              <span className="uncounted-text">
                {row.status === "partial" ? "Partly counted — " : "Not counted — "}+{fmtAmount(u.amount, u.unit ?? "")} from {u.item} not converted
              </span>{" "}
              {u.resolvable && u.food_id !== null && <Link to={`/foods/${u.food_id}#forms`}>Choose form</Link>}
            </li>
          ))}
        </ul>
      )}
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
      <h2>Where this day's energy data came from</h2>
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

function EntryItem({
  e,
  editing,
  onEdit,
  onDone,
  onDelete,
  deleting,
}: {
  e: LogEntry;
  editing: boolean;
  onEdit: () => void;
  onDone: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const time = new Date(e.consumed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <li className={`entry ${e.trust_level === "unverified" ? "entry-unverified" : ""}`}>
      <div className="entry-main">
        <div className="entry-text">
          <strong>{e.label}</strong>{" "}
          <span className="muted">
            {fmtNum(e.quantity)} {unitText(e.unit)}
            {e.weighed_state === "cooked" ? " (weighed cooked)" : ""}
            {e.grams ? ` · ${fmtNum(e.grams)} g` : ""} · {time}
          </span>
        </div>
        <div className="entry-actions">
          <TrustBadge level={e.trust_level} />
          <button type="button" className="btn-link" onClick={editing ? onDone : onEdit} aria-expanded={editing} aria-label={`Edit ${e.label}`}>
            Edit
          </button>
          <button type="button" className="btn-link danger" onClick={onDelete} disabled={deleting} aria-label={`Delete ${e.label}`}>
            Delete
          </button>
        </div>
      </div>
      {editing ? (
        <EntryEditor entry={e} onDone={onDone} />
      ) : (
        <>
          <MacroLine values={e.nutrients} />
          <Notes notes={e.calc_notes} />
          {e.note && <div className="muted small">Note: {e.note}</div>}
        </>
      )}
    </li>
  );
}

type Notice = { ok: boolean; text: string; goTo?: string };

/** Inline "copy to another day" form. */
function CopyForm({
  fromDate,
  meal,
  defaultTo,
  onDone,
  onCancel,
}: {
  fromDate: string;
  meal?: Meal;
  defaultTo: string;
  onDone: (n: Notice) => void;
  onCancel: () => void;
}) {
  const [to, setTo] = useState(defaultTo);
  const [toMeal, setToMeal] = useState<Meal | "">(meal ?? "");
  const qc = useQueryClient();
  const copy = useMutation({
    mutationFn: () => api.copyLog({ from_date: fromDate, to_date: to, meal: meal ?? null, to_meal: meal && toMeal && toMeal !== meal ? toMeal : null }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["day"] });
      onDone({ ok: true, text: `Copied ${created.length} entr${created.length === 1 ? "y" : "ies"} to ${fmtDay(to)}.`, goTo: to });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 404) onDone({ ok: false, text: "There was nothing to copy." });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (to) copy.mutate();
  }
  return (
    <form className="inline-panel" onSubmit={submit} aria-label={meal ? `Copy ${meal} to another day` : "Copy day to another day"}>
      <div className="row wrap align-end">
        <Field label="Copy to day">
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} required />
        </Field>
        {meal && (
          <Field label="As meal">
            <select value={toMeal} onChange={(e) => setToMeal(e.target.value as Meal)}>
              {MEALS.map((m) => (
                <option key={m} value={m}>
                  {mealLabel(m)}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="row">
          <button type="submit" className="btn btn-primary btn-sm" disabled={copy.isPending || !to}>
            {copy.isPending ? "Copying…" : "Copy"}
          </button>
          <button type="button" className="btn btn-sm" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
      <p className="muted small">Entries keep their time of day and are recalculated from current food data.</p>
      {!(copy.error instanceof ApiError && copy.error.status === 404) && <ErrorBox error={copy.error} />}
    </form>
  );
}

function SaveMealForm({ date, meal, onDone, onCancel }: { date: string; meal: Meal; onDone: (n: Notice) => void; onCancel: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const save = useMutation({
    mutationFn: () => api.savedMealFromLog(name.trim(), date, meal),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["saved-meals"] });
      onDone({ ok: true, text: `Saved “${m.name}” with ${m.items.length} item${m.items.length === 1 ? "" : "s"}. Log it from Add → Saved meals.` });
    },
  });
  return (
    <form
      className="inline-panel"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) save.mutate();
      }}
      aria-label={`Save ${meal} as a meal`}
    >
      <div className="row wrap align-end">
        <Field label="Name for this meal">
          <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} placeholder={`e.g. Usual ${meal}`} required autoFocus />
        </Field>
        <div className="row">
          <button type="submit" className="btn btn-primary btn-sm" disabled={!name.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save meal"}
          </button>
          <button type="button" className="btn btn-sm" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
      <ErrorBox error={save.error} />
    </form>
  );
}

function Targets({ s, pinned }: { s: DaySummary; pinned: string[] }) {
  const { byCode, list } = useNutrients();
  const order = (code: string) => {
    const i = list.findIndex((n) => n.code === code);
    return i === -1 ? 999 : i;
  };
  const [showAll, setShowAll] = useState(() => readPref(SHOW_ALL_PREF) === "1");
  const visible = (r: Evaluation) => showAll || CORE.includes(r.code) || pinned.includes(r.code) || isFlagged(r);
  const shown = s.evaluation.filter(visible);
  const hidden = s.evaluation.length - shown.length;
  const pinnedNoTarget = pinned.filter((c) => !s.evaluation.some((r) => r.code === c));

  function toggle() {
    const next = !showAll;
    setShowAll(next);
    writePref(SHOW_ALL_PREF, next ? "1" : "0");
  }

  return (
    <section className="card">
      <div className="row between wrap">
        <h2>Against your targets</h2>
        <button type="button" className="btn btn-sm" onClick={toggle} aria-expanded={showAll} aria-controls="target-list">
          {showAll ? "Show key nutrients only" : `Show all nutrients${hidden > 0 ? ` (${hidden} more)` : ""}`}
        </button>
      </div>
      <p className="muted small">
        {showAll ? (
          <>All nutrients with a target. </>
        ) : (
          <>
            Energy, macros, anything flagged and your <Link to="/profile#pinned">pinned nutrients</Link>.{" "}
          </>
        )}
        Ticks mark <span className="key key-min">min</span> <span className="key key-target">target</span>{" "}
        <span className="key key-max">upper limit</span>. Where an upper limit applies only to supplements, the darker bar shows supplement intake.
      </p>
      <div id="target-list">
        {GROUPS.map((g) => {
          const rows = shown
            .filter((r) => g.categories.includes(byCode[r.code]?.category ?? "other"))
            .sort((a, b) => order(a.code) - order(b.code));
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
      </div>
      {pinnedNoTarget.length > 0 && (
        <div className="target-group">
          <h3>Pinned (no target)</h3>
          <ul className="plain-list">
            {pinnedNoTarget.map((c) => (
              <li key={c} className="target-row row between">
                <span className="target-name">{nutrientName(byCode, c)}</span>
                <span className="target-amount">{fmtAmount(s.totals[c] ?? 0, byCode[c]?.unit)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export default function TodayPage() {
  const [day, setDay] = useState<string | null>(null);
  const qc = useQueryClient();
  const { byCode } = useNutrients();
  const summary = useQuery({ queryKey: ["day", day], queryFn: () => api.day(day ?? undefined) });
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const [editing, setEditing] = useState<number | null>(null);
  const [panel, setPanel] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const del = useMutation({
    mutationFn: api.deleteLog,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });
  const copyPrev = useMutation({
    mutationFn: (meal: Meal) => api.copyLog({ from_date: addDays(shownDay, -1), to_date: shownDay, meal }),
    onMutate: () => setNotice(null),
    onSuccess: (created, meal) => {
      qc.invalidateQueries({ queryKey: ["day"] });
      setNotice({ ok: true, text: `Copied ${created.length} ${meal} entr${created.length === 1 ? "y" : "ies"} from ${prevLabel}.` });
    },
    onError: (err, meal) => {
      if (err instanceof ApiError && err.status === 404) setNotice({ ok: false, text: `Nothing was logged for ${meal} ${prevLabel}, so there was nothing to copy.` });
    },
  });

  const s = summary.data;
  const shownDay = day ?? s?.date ?? "";
  const isToday = shownDay === todayISO();
  const prevLabel = isToday ? "yesterday" : `on ${fmtDay(addDays(shownDay || todayISO(), -1))}`;
  const copyDefault = isToday ? addDays(shownDay, 1) : todayISO();

  function go(d: string | null) {
    setDay(d);
    setEditing(null);
    setPanel(null);
    setNotice(null);
  }

  function finish(n: Notice) {
    setPanel(null);
    setNotice(n);
  }

  const emptyMeals = s ? MEALS.filter((m) => !s.entries.some((e) => e.meal === m)) : [];

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{isToday || !shownDay ? "Today" : fmtDay(shownDay)}</h1>
        <div className="row wrap day-controls">
          <div className="row">
            <button type="button" className="btn" onClick={() => shownDay && go(addDays(shownDay, -1))} aria-label="Previous day">
              ‹
            </button>
            <input type="date" value={shownDay} onChange={(e) => go(e.target.value || null)} aria-label="Day" className="date-input" />
            <button type="button" className="btn" onClick={() => shownDay && go(addDays(shownDay, 1))} aria-label="Next day">
              ›
            </button>
          </div>
          <Link to="/log" className="btn btn-primary">
            + Add entry
          </Link>
        </div>
      </div>

      <ErrorBox error={summary.error || del.error || (copyPrev.error instanceof ApiError && copyPrev.error.status === 404 ? null : copyPrev.error)} />
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
            <div className="row between wrap">
              <h2>Log</h2>
              {s.entries.length > 0 && (
                <button
                  type="button"
                  className="btn btn-sm"
                  aria-expanded={panel === "copy-day"}
                  onClick={() => setPanel(panel === "copy-day" ? null : "copy-day")}
                >
                  Copy day to…
                </button>
              )}
            </div>
            {panel === "copy-day" && (
              <CopyForm fromDate={shownDay} defaultTo={copyDefault} onDone={finish} onCancel={() => setPanel(null)} />
            )}
            {notice && (
              <div className={`result ${notice.ok ? "result-ok" : "result-info"}`} role="status">
                <span aria-hidden="true">{notice.ok ? "✓" : "ℹ"}</span> {notice.text}{" "}
                {notice.goTo && notice.goTo !== shownDay && (
                  <button type="button" className="btn-link" onClick={() => go(notice.goTo!)}>
                    View {fmtDay(notice.goTo)}
                  </button>
                )}
              </div>
            )}
            {s.entries.length === 0 && <p className="muted">Nothing logged for this day.</p>}
            {MEALS.map((meal) => {
              const items = s.entries.filter((e) => e.meal === meal);
              if (!items.length) return null;
              const kcal = items.reduce((sum, e) => sum + (e.nutrients.energy_kcal ?? 0), 0);
              return (
                <div key={meal} className="meal-group">
                  <div className="meal-head">
                    <h3>
                      {mealLabel(meal)} <span className="muted small">{Math.round(kcal)} kcal</span>
                    </h3>
                    <div className="row wrap meal-actions">
                      <button
                        type="button"
                        className="btn-link small"
                        aria-expanded={panel === `copy:${meal}`}
                        onClick={() => setPanel(panel === `copy:${meal}` ? null : `copy:${meal}`)}
                      >
                        Copy to…
                      </button>
                      <button
                        type="button"
                        className="btn-link small"
                        aria-expanded={panel === `save:${meal}`}
                        onClick={() => setPanel(panel === `save:${meal}` ? null : `save:${meal}`)}
                      >
                        Save as meal…
                      </button>
                    </div>
                  </div>
                  {panel === `copy:${meal}` && (
                    <CopyForm fromDate={shownDay} meal={meal} defaultTo={copyDefault} onDone={finish} onCancel={() => setPanel(null)} />
                  )}
                  {panel === `save:${meal}` && <SaveMealForm date={shownDay} meal={meal} onDone={finish} onCancel={() => setPanel(null)} />}
                  <ul className="plain-list">
                    {items.map((e) => (
                      <EntryItem
                        key={e.id}
                        e={e}
                        editing={editing === e.id}
                        onEdit={() => setEditing(e.id)}
                        onDone={() => setEditing(null)}
                        onDelete={() => del.mutate(e.id)}
                        deleting={del.isPending}
                      />
                    ))}
                  </ul>
                </div>
              );
            })}
            {emptyMeals.length > 0 && (
              <div className="copy-prev">
                <span className="muted small">Same as {prevLabel}?</span>
                <div className="row wrap">
                  {emptyMeals.map((m) => (
                    <button key={m} type="button" className="btn btn-sm" disabled={copyPrev.isPending} onClick={() => copyPrev.mutate(m)}>
                      Copy {isToday ? "yesterday's" : "previous day's"} {m}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          {s.evaluation.length > 0 && <Targets s={s} pinned={profile.data?.pinned_nutrients ?? []} />}

          <EnergyByTrust data={s.energy_by_trust} />

          {s.other_components.length > 0 && (
            <details className="card components-details">
              <summary>
                Other supplement components <span className="chip">{s.other_components.length}</span>
              </summary>
              <p className="muted small">Label ingredients that aren't in the nutrient catalog or couldn't be converted.</p>
              <ComponentList items={s.other_components} title={null} />
            </details>
          )}
          <TrustLegend />
        </>
      )}
    </div>
  );
}
