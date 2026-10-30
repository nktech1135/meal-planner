import { useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { QuantityFields, unitChoices, WeighedFields } from "../components/AmountFields";
import { ErrorBox, Field, Loading, MacroLine } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { TrustBadge } from "../components/TrustBadge";
import { addDays, basisLabel, fmtDay, fmtNum, fmtShortDate, mealLabel, mondayOf, nutrientName, parseNum, todayISO, unitText, useMedia, useNutrients } from "../lib";
import { MEALS, type FoodSummary, type Meal, type PlanDay, type PlanItem, type PlanItemUpdate, type WeighedState } from "../types";
import { Button, focusSoon, rescueFocus, tabPanelProps, TabList, useAnnounce, useAnnounceText, useReturnFocus, VisuallyHidden } from "../components/a11y";

const ORIGIN: Record<string, string | null> = { manual: null, advisor: "from advisor", copy: "copied", saved_meal: "saved meal" };

function invalidateAfterLog(qc: QueryClient) {
  for (const key of ["plan", "day", "suggestions", "trends", "range", "shopping"]) qc.invalidateQueries({ queryKey: [key] });
}

const longDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });

type AddMode = "food" | "recipe" | "saved";

/** Add a food, recipe or saved meal to one day of the plan. */
function AddItem({ date, defaultMeal, onDone }: { date: string; defaultMeal: Meal; onDone: (msg: string) => void }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<AddMode>("food");
  const [meal, setMeal] = useState<Meal>(defaultMeal);
  const [picked, setPicked] = useState<FoodSummary | null>(null);
  const [recipeId, setRecipeId] = useState<number | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [savedMeal, setSavedMeal] = useState<Meal | "">("");
  const [quantity, setQuantity] = useState("100");
  const [unit, setUnit] = useState("g");
  const [weighed, setWeighed] = useState<WeighedState>("as_is");
  const [yieldId, setYieldId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const food = useQuery({ queryKey: ["food", picked?.id], queryFn: () => api.food(picked!.id), enabled: !!picked });
  const recipes = useQuery({ queryKey: ["recipes"], queryFn: api.recipes, enabled: mode === "recipe" });
  const saved = useQuery({ queryKey: ["saved-meals"], queryFn: api.savedMeals, enabled: mode === "saved" });
  const recipe = recipes.data?.find((r) => r.id === recipeId) ?? null;
  const qty = parseNum(quantity);
  const selectedRef = useRef<HTMLDivElement>(null);

  const add = useMutation({
    mutationFn: async () => {
      if (mode === "saved") {
        const items = await api.planSavedMeal(savedId!, date, savedMeal || null);
        return `Added ${items.length} item${items.length === 1 ? "" : "s"} from the saved meal.`;
      }
      const item = await api.addPlanItem({
        date,
        meal,
        food_id: mode === "food" ? picked!.id : null,
        recipe_id: mode === "recipe" ? recipeId : null,
        quantity: qty!,
        unit,
        weighed_state: mode === "food" ? weighed : "as_is",
        yield_id: mode === "food" && weighed === "cooked" ? yieldId : null,
        note: note.trim(),
      });
      return `Added ${item.label}.`;
    },
    onSuccess: (msg) => {
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      onDone(msg);
    },
  });

  function pickFood(f: FoodSummary, focus = true) {
    setPicked(f);
    if (focus) focusSoon(() => selectedRef.current);
    setWeighed("as_is");
    setYieldId(null);
    setUnit(f.basis === "serving" ? "serving" : "g");
    setQuantity(f.basis === "serving" ? "1" : "100");
    if (f.kind === "supplement") setMeal("supplement");
  }
  function switchMode(m: AddMode) {
    setMode(m);
    if (m === "recipe") {
      setUnit("serving");
      setQuantity("1");
    } else if (m === "food" && picked) pickFood(picked, false);
  }

  const valid =
    mode === "saved"
      ? !!savedId
      : !!qty && qty > 0 && (mode === "food" ? !!picked && !(weighed === "cooked" && !yieldId) : !!recipeId);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (valid) add.mutate();
  }

  const tabsId = `plan-add-${date}`;

  return (
    <form className="inline-panel stack-sm plan-add" onSubmit={submit} aria-label={`Add to ${longDay(date)}`}>
      <TabList
        id={tabsId}
        className="small"
        label="What to add"
        value={mode}
        onChange={switchMode}
        tabs={[
          { value: "food", label: "Food" },
          { value: "recipe", label: "Recipe" },
          { value: "saved", label: "Saved meal" },
        ]}
      />
      <div className="stack-sm" {...tabPanelProps(tabsId, mode)}>
      <Field label="Meal">
        {mode === "saved" ? (
          <select value={savedMeal} onChange={(e) => setSavedMeal(e.target.value as Meal | "")}>
            <option value="">The saved meal's usual meal</option>
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

      {mode === "food" &&
        (picked ? (
          <div className="selected" ref={selectedRef} tabIndex={-1} role="group" aria-label={`Chosen: ${picked.name}`}>
            <div className="min-0">
              <strong>{picked.name}</strong> {picked.brand && <span className="muted">· {picked.brand}</span>}
              <div className="row wrap small">
                <TrustBadge level={picked.trust_level} />
                <span className="muted">{basisLabel(picked)}</span>
              </div>
            </div>
            <button type="button" className="btn-link" onClick={() => setPicked(null)}>
              Change<VisuallyHidden> food</VisuallyHidden>
            </button>
          </div>
        ) : (
          <FoodPicker onPick={pickFood} />
        ))}

      {mode === "recipe" && (
        <Field label="Recipe">
          <select
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
        <p className="muted small">
          No recipes yet. <Link to="/recipes/new">Create one</Link>.
        </p>
      )}

      {mode === "saved" && (
        <Field label="Saved meal">
          <select value={savedId ?? ""} onChange={(e) => setSavedId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Choose a saved meal…</option>
            {saved.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.items.length} items)
              </option>
            ))}
          </select>
        </Field>
      )}
      {mode === "saved" && saved.data?.length === 0 && <p className="muted small">No saved meals yet. Save one from a meal on the Today page.</p>}

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
        </>
      )}
      </div>
      <ErrorBox error={add.error || food.error} />
      <div className="row wrap">
        <Button type="submit" className="btn btn-primary btn-sm" disabled={!valid || add.isPending}>
          {add.isPending ? "Adding…" : "Add to plan"}
        </Button>
        <button type="button" className="btn btn-sm" onClick={() => onDone("")}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ItemEditor({ item, onDone }: { item: PlanItem; onDone: () => void }) {
  const qc = useQueryClient();
  const food = useQuery({ queryKey: ["food", item.food_id], queryFn: () => api.food(item.food_id!), enabled: !!item.food_id });
  const recipe = useQuery({ queryKey: ["recipe", item.recipe_id], queryFn: () => api.recipe(item.recipe_id!), enabled: !!item.recipe_id });
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [unit, setUnit] = useState(item.unit);
  const [weighed, setWeighed] = useState<WeighedState>(item.weighed_state);
  const [yieldId, setYieldId] = useState<number | null>(item.yield_id);
  const [meal, setMeal] = useState<Meal>(item.meal);
  const [date, setDate] = useState(item.date);
  const [note, setNote] = useState(item.note);
  const changes: PlanItemUpdate = {};
  const q = parseNum(quantity);
  if (q !== null && q !== item.quantity) changes.quantity = q;
  if (unit !== item.unit) changes.unit = unit;
  if (weighed !== item.weighed_state) changes.weighed_state = weighed;
  const y = weighed === "cooked" ? yieldId : null;
  if (y !== item.yield_id) changes.yield_id = y;
  if (meal !== item.meal) changes.meal = meal;
  if (date && date !== item.date) changes.date = date;
  if (note !== item.note) changes.note = note;
  const invalid = !q || q <= 0 || (weighed === "cooked" && !yieldId) || !date;
  const save = useMutation({
    mutationFn: () => api.updatePlanItem(item.id, changes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      onDone();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (invalid) return;
    if (Object.keys(changes).length === 0) onDone();
    else save.mutate();
  }
  return (
    <form className="entry-editor stack-sm" onSubmit={submit} aria-label={`Edit planned ${item.label}`}>
      {(food.isLoading || recipe.isLoading) && <Loading />}
      {food.data && (
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
      <QuantityFields quantity={quantity} unit={unit} options={unitChoices(food.data, recipe.data, weighed, unit)} onQuantity={setQuantity} onUnit={setUnit} />
      <div className="grid-2">
        <Field label="Meal">
          <select value={meal} onChange={(e) => setMeal(e.target.value as Meal)}>
            {MEALS.map((m) => (
              <option key={m} value={m}>
                {mealLabel(m)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Day">
          <input type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      <Field label="Note">
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <ErrorBox error={save.error || food.error || recipe.error} />
      <div className="row wrap">
        <Button type="submit" className="btn btn-primary btn-sm" disabled={invalid || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <button type="button" className="btn btn-sm" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function PlanItemRow({
  item,
  editing,
  onEdit,
  onDone,
  dayHeading,
}: {
  item: PlanItem;
  editing: boolean;
  onEdit: () => void;
  onDone: () => void;
  dayHeading: () => HTMLElement | null;
}) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const editButton = useReturnFocus<HTMLButtonElement>(editing);
  const log = useMutation({
    mutationFn: () => api.logPlanItem(item.id),
    onSuccess: () => {
      invalidateAfterLog(qc);
      announce(`Logged ${item.label}.`);
      rescueFocus(() => editButton.current);
    },
    onError: () => invalidateAfterLog(qc),
  });
  const del = useMutation({
    mutationFn: () => api.deletePlanItem(item.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      announce(`Removed ${item.label} from the plan.`);
      rescueFocus(dayHeading);
    },
  });
  const logged = item.logged_entry_id !== null;
  const origin = ORIGIN[item.origin];
  const kcal = item.nutrients.energy_kcal;
  const alreadyLogged = log.error instanceof ApiError && log.error.status === 409;
  return (
    <li className={`entry plan-item ${logged ? "is-logged" : ""}`}>
      <div className="entry-main">
        <div className="entry-text">
          <strong>{item.label}</strong>{" "}
          <span className="muted">
            {fmtNum(item.quantity)} {unitText(item.unit)}
            {item.weighed_state === "cooked" ? " (weighed cooked)" : ""}
            {kcal !== undefined ? ` · ${Math.round(kcal)} kcal` : ""}
          </span>
          {(logged || origin || item.trust_level === "unverified") && (
            <div className="row wrap small plan-badges">
              {logged && (
                <span className="chip chip-ok">
                  <span aria-hidden="true">✓ </span>logged
                </span>
              )}
              {origin && <span className="chip">{origin}</span>}
              {item.trust_level === "unverified" && <TrustBadge level={item.trust_level} />}
            </div>
          )}
        </div>
        <div className="entry-actions">
          {!logged && (
            <Button type="button" className="btn btn-sm" onClick={() => log.mutate()} disabled={log.isPending || !!item.error}>
              {log.isPending ? "Logging…" : "Log"}
              <VisuallyHidden> {item.label}</VisuallyHidden>
            </Button>
          )}
          <button ref={editButton} type="button" className="btn-link" onClick={editing ? onDone : onEdit} aria-expanded={editing}>
            Edit<VisuallyHidden> {item.label}</VisuallyHidden>
          </button>
          <Button type="button" className="btn-link danger" onClick={() => del.mutate()} disabled={del.isPending}>
            Remove<VisuallyHidden> {item.label} from the plan</VisuallyHidden>
          </Button>
        </div>
      </div>
      {item.error && (
        <p className="warn-text small" role="note">
          <span aria-hidden="true">⚠ </span>
          {item.error}
        </p>
      )}
      {item.note && !editing && <div className="muted small">Note: {item.note}</div>}
      {editing && <ItemEditor item={item} onDone={onDone} />}
      {alreadyLogged ? <p className="muted small">Already logged.</p> : <ErrorBox error={log.error || del.error} />}
    </li>
  );
}

function DayTotals({ day }: { day: PlanDay }) {
  const { byCode } = useNutrients();
  const row = (c: string) => day.evaluation.find((r) => r.code === c);
  const energy = row("energy_kcal");
  const kcal = day.totals.energy_kcal ?? 0;
  const over = day.evaluation.filter((r) => r.status === "above_max");
  const macro = (c: string, short: string, long: string) => {
    const r = row(c);
    const v = day.totals[c] ?? 0;
    const goal = r?.target ?? r?.min ?? null;
    return (
      <span key={c} className="nowrap">
        <span aria-hidden="true">{short}</span>
        <VisuallyHidden>{long}</VisuallyHidden> {fmtNum(v)}
        {goal !== null && (
          <span className="muted">
            <span aria-hidden="true">/</span>
            <VisuallyHidden> of </VisuallyHidden>
            {fmtNum(goal)}
          </span>
        )}{" "}
        g
      </span>
    );
  };
  if (!day.items.length) return null;
  return (
    <div className="plan-totals small">
      <div className="row wrap">
        <strong className="nowrap">
          {Math.round(kcal).toLocaleString()}
          {energy?.target ? (
            <span className="muted">
              {" "}
              <span aria-hidden="true">/</span>
              <VisuallyHidden>of</VisuallyHidden> {fmtNum(energy.target)}
            </span>
          ) : null}{" "}
          kcal
        </strong>
        <VisuallyHidden>planned.</VisuallyHidden>
        {macro("protein_g", "P", "protein")}
        {macro("fat_g", "F", "fat")}
        {macro("carbs_g", "C", "carbs")}
      </div>
      {over.length > 0 && (
        <p className="danger-text" role="note">
          <span aria-hidden="true">⚠ </span>Above limit: {over.map((r) => `${nutrientName(byCode, r.code)} (${fmtNum(r.limit_amount)} / ${fmtNum(r.max)} ${byCode[r.code]?.unit ?? ""})`).join(", ")}
        </p>
      )}
    </div>
  );
}

function CopyDay({ from, onDone }: { from: string; onDone: (msg: string, goTo?: string) => void }) {
  const qc = useQueryClient();
  const [to, setTo] = useState(addDays(from, 1));
  const copy = useMutation({
    mutationFn: () => api.copyPlan(from, from, to),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      onDone(`Copied ${r.copied} item${r.copied === 1 ? "" : "s"} to ${fmtDay(to)}.`, to);
    },
  });
  return (
    <form
      className="inline-panel"
      onSubmit={(e) => {
        e.preventDefault();
        if (to) copy.mutate();
      }}
      aria-label={`Copy ${longDay(from)} to another day`}
    >
      <div className="row wrap align-end">
        <Field label="Copy to day">
          <input type="date" required value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <div className="row">
          <Button type="submit" className="btn btn-primary btn-sm" disabled={copy.isPending}>
            {copy.isPending ? "Copying…" : "Copy"}
          </Button>
          <button type="button" className="btn btn-sm" onClick={() => onDone("")}>
            Cancel
          </button>
        </div>
      </div>
      <ErrorBox error={copy.error} />
    </form>
  );
}

function DayCard({ day, onGo, panelProps }: { day: PlanDay; onGo: (d: string) => void; panelProps?: Record<string, string> }) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ text: string; goTo?: string } | null>(null);
  const noticeRef = useAnnounceText<HTMLDivElement>();
  const heading = useRef<HTMLHeadingElement>(null);
  const copyButton = useReturnFocus<HTMLButtonElement>(panel === "copy");
  const addButton = useReturnFocus<HTMLButtonElement>(panel === "add");
  const dayName = longDay(day.date);
  const logAll = useMutation({
    mutationFn: (meal: Meal | null) => api.logPlanDay(day.date, meal),
    onMutate: () => setNotice(null),
    onSuccess: (entries) => {
      invalidateAfterLog(qc);
      setNotice({ text: `Logged ${entries.length} item${entries.length === 1 ? "" : "s"}.` });
      rescueFocus(() => heading.current);
    },
  });
  const isToday = day.date === todayISO();
  const unlogged = day.items.filter((i) => i.logged_entry_id === null && !i.error).length;
  const finish = (text: string, goTo?: string) => {
    setPanel(null);
    setNotice(text ? { text, goTo } : null);
  };

  return (
    <section className={`card stack-sm plan-day ${isToday ? "is-today" : ""}`} aria-labelledby={`day-${day.date}`} {...panelProps}>
      <div className="row between wrap">
        <h2 id={`day-${day.date}`} className="h-card" ref={heading}>
          {dayName} {isToday && <span className="chip chip-ok">today</span>}
        </h2>
        <div className="row wrap meal-actions">
          {unlogged > 0 && (
            <Button type="button" className="btn btn-sm" disabled={logAll.isPending} onClick={() => logAll.mutate(null)}>
              {logAll.isPending && logAll.variables === null ? "Logging…" : `Log all (${unlogged})`}
              <VisuallyHidden> for {dayName}</VisuallyHidden>
            </Button>
          )}
          {day.items.length > 0 && (
            <button
              ref={copyButton}
              type="button"
              className="btn-link small"
              aria-expanded={panel === "copy"}
              onClick={() => setPanel(panel === "copy" ? null : "copy")}
            >
              Copy day to…<VisuallyHidden> ({dayName})</VisuallyHidden>
            </button>
          )}
        </div>
      </div>
      <DayTotals day={day} />
      {panel === "copy" && <CopyDay from={day.date} onDone={finish} />}
      {notice && (
        <div ref={noticeRef} className="result result-ok">
          <span aria-hidden="true">✓</span> {notice.text}{" "}
          {notice.goTo && (
            <button type="button" className="btn-link" onClick={() => onGo(notice.goTo!)}>
              View {fmtDay(notice.goTo)}
            </button>
          )}
        </div>
      )}
      <ErrorBox error={logAll.error} />
      {day.items.length === 0 && panel !== "add" && <p className="muted small">Nothing planned.</p>}
      {MEALS.map((meal) => {
        const items = day.items.filter((i) => i.meal === meal);
        if (!items.length) return null;
        const kcal = items.reduce((s, i) => s + (i.nutrients.energy_kcal ?? 0), 0);
        const open = items.filter((i) => i.logged_entry_id === null && !i.error).length;
        return (
          <div key={meal} className="meal-group">
            <div className="meal-head">
              <h3>
                {mealLabel(meal)} <span className="muted small">{Math.round(kcal)} kcal</span>
              </h3>
              {open > 0 && open < unlogged && (
                <Button type="button" className="btn-link small" disabled={logAll.isPending} onClick={() => logAll.mutate(meal)}>
                  Log {meal}
                  <VisuallyHidden> for {dayName}</VisuallyHidden>
                </Button>
              )}
            </div>
            <ul className="plain-list">
              {items.map((i) => (
                <PlanItemRow
                  key={i.id}
                  item={i}
                  editing={editing === i.id}
                  onEdit={() => setEditing(i.id)}
                  onDone={() => setEditing(null)}
                  dayHeading={() => heading.current}
                />
              ))}
            </ul>
          </div>
        );
      })}
      {panel === "add" ? (
        <AddItem date={day.date} defaultMeal={day.items.length ? "dinner" : "breakfast"} onDone={(msg) => finish(msg)} />
      ) : (
        <div>
          <button ref={addButton} type="button" className="btn btn-sm" onClick={() => setPanel("add")}>
            + Add to {fmtDay(day.date) === "today" ? "today" : new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "long" })}
          </button>
        </div>
      )}
    </section>
  );
}

export default function PlanPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const phone = useMedia("(max-width: 640px)");
  const today = todayISO();
  const focus = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") ?? "") ? params.get("date")! : today;
  const start = mondayOf(focus);
  const end = addDays(start, 6);
  const plan = useQuery({ queryKey: ["plan", start, end], queryFn: () => api.plan(start, end), placeholderData: (prev) => prev });
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const noticeRef = useAnnounceText<HTMLDivElement>();
  const go = (d: string) => {
    setNotice(null);
    setParams(d === today ? {} : { date: d }, { replace: true });
  };
  const copyWeek = useMutation({
    mutationFn: () => api.copyPlan(start, end, addDays(start, 7)),
    onMutate: () => setNotice(null),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      setNotice({ ok: true, text: `Copied ${r.copied} item${r.copied === 1 ? "" : "s"} to the week of ${fmtShortDate(addDays(start, 7))}.` });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 404) setNotice({ ok: false, text: "Nothing is planned this week, so there was nothing to copy." });
    },
  });
  const days = plan.data ?? [];
  const shownDay = days.find((d) => d.date === focus) ?? days[0];
  const thisWeek = start === mondayOf(today);
  const shopStart = thisWeek ? today : start;
  const anything = days.some((d) => d.items.length > 0);

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Plan</h1>
        <div className="row wrap">
          <Link className="btn" to={`/plan/shopping?start=${shopStart}&end=${end}`}>
            Shopping list
          </Link>
        </div>
      </div>
      <div className="row wrap between plan-controls">
        <div className="row">
          <button type="button" className="btn" onClick={() => go(addDays(start, -7))} aria-label="Previous week">
            <span aria-hidden="true">‹</span>
          </button>
          <strong className="nowrap week-label" aria-live="polite">
            <VisuallyHidden>Week of </VisuallyHidden>
            {fmtShortDate(start)} – {fmtShortDate(end)}
          </strong>
          <button type="button" className="btn" onClick={() => go(addDays(start, 7))} aria-label="Next week">
            <span aria-hidden="true">›</span>
          </button>
        </div>
        <div className="row wrap">
          {!thisWeek && (
            <button type="button" className="btn btn-sm" onClick={() => go(today)}>
              Jump to today
            </button>
          )}
          <Button type="button" className="btn btn-sm" disabled={copyWeek.isPending || !anything} onClick={() => copyWeek.mutate()}>
            {copyWeek.isPending ? "Copying…" : "Copy this week to next week"}
          </Button>
        </div>
      </div>
      {notice && (
        <div ref={noticeRef} className={`result ${notice.ok ? "result-ok" : "result-info"}`}>
          <span aria-hidden="true">{notice.ok ? "✓" : "ℹ"}</span> {notice.text}{" "}
          {notice.ok && (
            <button type="button" className="btn-link" onClick={() => go(addDays(start, 7))}>
              View next week
            </button>
          )}
        </div>
      )}
      {!(copyWeek.error instanceof ApiError && copyWeek.error.status === 404) && <ErrorBox error={copyWeek.error} />}
      <ErrorBox error={plan.error} />
      {plan.isLoading && <Loading />}
      {days.length > 0 && (
        <p className="muted small">
          Plan meals ahead, then log them with one click when you eat them. Amounts and nutrients are worked out the same way as your log.{" "}
          {!anything && <>Nothing is planned for this week yet. The advisor can also propose meals for you.</>}
        </p>
      )}
      {phone && days.length > 0 && (
        <TabList
          id="plan-days"
          className="day-tabs"
          label="Day"
          value={shownDay?.date ?? ""}
          onChange={go}
          tabs={days.map((d) => ({
            value: d.date,
            label: (
              <>
                {/* Compact on screen ("M 26"); the full day for screen readers. */}
                <span className="day-tab-name" aria-hidden="true">
                  {new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: "narrow" })}
                </span>
                <span className="day-tab-num" aria-hidden="true">
                  {new Date(`${d.date}T12:00:00`).getDate()}
                </span>
                <span className={`day-tab-dot ${d.items.length ? "has" : ""}`} aria-hidden="true" />
                <VisuallyHidden>
                  {longDay(d.date)}
                  {d.items.length ? `, ${d.items.length} planned` : ""}
                </VisuallyHidden>
              </>
            ),
          }))}
        />
      )}
      <div className={`plan-week ${plan.isPlaceholderData && plan.isFetching ? "is-stale" : ""}`}>
        {phone
          ? shownDay && <DayCard key={shownDay.date} day={shownDay} onGo={go} panelProps={tabPanelProps("plan-days", shownDay.date)} />
          : days.map((d) => <DayCard key={d.date} day={d} onGo={go} />)}
      </div>
      {days.length > 0 && anything && (
        <details className="card">
          <summary>Week totals</summary>
          <div className="stack-sm plan-week-totals">
            {days
              .filter((d) => d.items.length)
              .map((d) => (
                <div key={d.date} className="row wrap small">
                  <strong className="week-total-day">{fmtShortDate(d.date)}</strong> <MacroLine values={d.totals} />
                </div>
              ))}
          </div>
        </details>
      )}
    </div>
  );
}
