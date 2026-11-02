import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Button, NewTab, rescueFocus, useAnnounce, VisuallyHidden } from "../components/a11y";
import { ErrorBox, Field, Loading } from "../components/common";
import { addDays, fmt1, fmtShortDate, parseNum, todayISO, useDebounced, useUnitSystem } from "../lib";
import type { Exercise, ExerciseImport, ExerciseInput, KcalMethod, UnitSystem } from "../types";

const M_PER_MI = 1609.344;
const distanceUnit = (u: UnitSystem) => (u === "imperial" ? "mi" : "km");
const toDistance = (m: number, u: UnitSystem) => m / (u === "imperial" ? M_PER_MI : 1000);
const fromDistance = (v: number, u: UnitSystem) => v * (u === "imperial" ? M_PER_MI : 1000);

const METHOD_LABEL: Record<KcalMethod, string> = {
  compendium: "Compendium METs",
  device: "device",
  entered: "entered",
  none: "not counted",
};

const SOURCE_LABEL: Record<Exercise["source"], string> = { manual: "", fit: "FIT file", tcx: "TCX file", gpx: "GPX file" };

function invalidate(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ["exercise"] });
  qc.invalidateQueries({ queryKey: ["day"] });
  qc.invalidateQueries({ queryKey: ["trends"] });
}

function fmtDuration(min: number): string {
  const total = Math.round(min);
  return total >= 60 ? `${Math.floor(total / 60)} h ${total % 60} min` : `${total} min`;
}

const numText = (v: number | null, f: (v: number) => number = (x) => x) => (v === null ? "" : String(Math.round(f(v) * 100) / 100));

function ActivityPicker({ code, label, onPick }: { code: string | null; label: string; onPick: (code: string | null, description: string) => void }) {
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim());
  const results = useQuery({ queryKey: ["activities", query], queryFn: () => api.activities(query), staleTime: Infinity });
  const options = results.data ?? [];
  const chosenShown = code !== null && options.some((a) => a.code === code);
  return (
    <div className="grid-2">
      <Field label="Find an activity" hint="Search the 2024 Adult Compendium of Physical Activities, e.g. “cycling 12 mph” or “yoga”.">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </Field>
      <Field label="Activity" error={results.error ? "Couldn't load activities" : undefined}>
        <select
          value={code ?? ""}
          onChange={(e) => {
            const a = options.find((o) => o.code === e.target.value);
            onPick(a?.code ?? null, a?.description ?? "");
          }}
        >
          <option value="">{options.length ? "— choose —" : query ? "No matches" : "Loading…"}</option>
          {code !== null && !chosenShown && <option value={code}>{label}</option>}
          {options.map((a) => (
            <option key={a.code} value={a.code}>
              {a.description} ({a.met} MET)
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}

function blank(): ExerciseInput {
  return { date: todayISO(), activity_code: null, name: "", duration_min: 0, distance_m: null, avg_hr: null, reported_kcal: null, note: "" };
}

function ExerciseForm({ units, editing, onDone }: { units: UnitSystem; editing: Exercise | null; onDone: () => void }) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const [form, setForm] = useState<ExerciseInput>(blank);
  const [activityLabel, setActivityLabel] = useState("");
  const [duration, setDuration] = useState("");
  const [distance, setDistance] = useState("");
  const [hr, setHr] = useState("");
  const [kcal, setKcal] = useState("");
  useEffect(() => {
    if (!editing) return;
    setForm({ ...editing });
    setActivityLabel(editing.activity_code ? editing.name : "");
    setDuration(numText(editing.duration_min));
    setDistance(numText(editing.distance_m, (m) => toDistance(m, units)));
    setHr(numText(editing.avg_hr));
    setKcal(numText(editing.reported_kcal));
  }, [editing, units]);

  function reset() {
    setForm(blank());
    setActivityLabel("");
    setDuration("");
    setDistance("");
    setHr("");
    setKcal("");
  }

  const minutes = parseNum(duration);
  const dist = parseNum(distance);
  const body = (): ExerciseInput => ({
    ...form,
    // The activity's own description is used when the name is left as it.
    name: form.activity_code && form.name === activityLabel ? "" : form.name.trim(),
    duration_min: minutes ?? 0,
    distance_m: dist === null ? null : Math.round(fromDistance(dist, units)),
    avg_hr: parseNum(hr),
    reported_kcal: parseNum(kcal),
    note: form.note.trim(),
  });
  const save = useMutation({
    mutationFn: () => (editing ? api.updateExercise(editing.id, body()) : api.addExercise(body())),
    onSuccess: (x) => {
      invalidate(qc);
      announce(`Saved ${x.name}: ${Math.round(x.kcal)} kcal added to ${fmtShortDate(x.date)}'s energy target.`);
      reset();
      onDone();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (minutes && minutes > 0) save.mutate();
  }
  const set = <K extends keyof ExerciseInput>(k: K, v: ExerciseInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <form className="stack-sm" onSubmit={submit} aria-label={editing ? `Edit ${editing.name}` : "Log a workout"}>
      <ActivityPicker
        code={form.activity_code}
        label={activityLabel}
        onPick={(code, description) => {
          setForm((f) => ({ ...f, activity_code: code, name: !f.name || f.name === activityLabel ? description : f.name }));
          setActivityLabel(description);
        }}
      />
      <div className="grid-4">
        <Field label="Date">
          <input id="exercise-date" type="date" required value={form.date} max={todayISO()} onChange={(e) => set("date", e.target.value)} />
        </Field>
        <Field label="Duration (min)">
          <input type="number" inputMode="decimal" step="any" min="1" max="1440" required value={duration} onChange={(e) => setDuration(e.target.value)} />
        </Field>
        <Field label={`Distance (${distanceUnit(units)}, optional)`}>
          <input type="number" inputMode="decimal" step="any" min="0" value={distance} onChange={(e) => setDistance(e.target.value)} />
        </Field>
        <Field label="Average heart rate (optional)">
          <input type="number" inputMode="numeric" step="1" min="21" max="259" value={hr} onChange={(e) => setHr(e.target.value)} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Name" hint={form.activity_code ? "Defaults to the activity; change it if you like." : "Required without an activity."}>
          <input value={form.name} maxLength={200} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Calories from a device or machine (optional)" hint="Total kcal it reported. Used instead of the MET estimate.">
          <input type="number" inputMode="decimal" step="any" min="0" value={kcal} onChange={(e) => setKcal(e.target.value)} />
        </Field>
      </div>
      <Field label="Note (optional)">
        <input value={form.note} maxLength={500} onChange={(e) => set("note", e.target.value)} />
      </Field>
      <ErrorBox error={save.error} />
      <div className="row wrap">
        <Button type="submit" className="btn btn-primary" disabled={save.isPending || !minutes || (!form.activity_code && !form.name.trim())}>
          {save.isPending ? "Saving…" : editing ? "Save changes" : "Log workout"}
        </Button>
        {editing && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              reset();
              onDone();
              rescueFocus(() => document.getElementById("exercise-date"));
            }}
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function ImportSection() {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const fileInput = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [since, setSince] = useState("");
  const [result, setResult] = useState<ExerciseImport | null>(null);
  const run = useMutation({
    mutationFn: () => api.importExercise(files, since || null),
    onMutate: () => setResult(null),
    onSuccess: (r) => {
      invalidate(qc);
      setResult(r);
      setFiles([]);
      if (fileInput.current) fileInput.current.value = "";
      announce(`Imported ${r.imported} workout${r.imported === 1 ? "" : "s"}.`);
    },
  });
  return (
    <section className="card stack-sm" aria-labelledby="import-title">
      <h2 id="import-title">Import from files</h2>
      <p className="muted small">
        Upload <code>.fit</code>, <code>.tcx</code> or <code>.gpx</code> activity files (also gzipped), or a <code>.zip</code> of them. Workouts already
        imported are skipped. Calories recorded by the device are used when the file has them; otherwise energy is estimated from the activity type.
      </p>
      <details className="small">
        <summary>Where to get files</summary>
        <ul>
          <li>
            <strong>Strava:</strong> Settings → My Account → Download or Delete Your Account → Request your archive. Upload the whole <code>.zip</code>{" "}
            Strava emails you; only the files in its <code>activities</code> folder are read. (This app doesn't connect to Strava directly: Strava's API
            terms don't allow its data to be used with an AI advisor.)
          </li>
          <li>
            <strong>Garmin Connect:</strong> open an activity, then the gear menu → Export Original (a <code>.zip</code> holding the <code>.fit</code> file).
          </li>
          <li>
            <strong>Other watches and apps</strong> (Wahoo, Polar, Coros, Suunto, Apple Watch through export apps): look for “export FIT”, “TCX” or “GPX”.
          </li>
        </ul>
      </details>
      <div className="grid-2">
        <Field label="Files">
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".fit,.tcx,.gpx,.gz,.zip"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </Field>
        <Field label="Only workouts on or after (optional)" hint="Handy for a large archive.">
          <input type="date" value={since} max={todayISO()} onChange={(e) => setSince(e.target.value)} />
        </Field>
      </div>
      <ErrorBox error={run.error} />
      <div className="row wrap">
        <Button type="button" className="btn btn-primary" disabled={!files.length || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Importing…" : `Import ${files.length || ""} file${files.length === 1 ? "" : "s"}`}
        </Button>
      </div>
      {result && (
        <div className={`result ${result.error_count ? "result-info" : "result-ok"}`}>
          <p>
            Imported {result.imported} workout{result.imported === 1 ? "" : "s"}
            {result.skipped_duplicates > 0 && `, skipped ${result.skipped_duplicates} already imported`}
            {result.skipped_before_since > 0 && `, skipped ${result.skipped_before_since} before ${fmtShortDate(since)}`}.
          </p>
          {result.error_count > 0 && (
            <>
              <p>
                {result.error_count} file{result.error_count === 1 ? "" : "s"} couldn't be read:
              </p>
              <ul className="small">
                {result.errors.map((e, i) => (
                  <li key={i}>
                    {e.file}: {e.error}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

export default function ExercisePage() {
  const qc = useQueryClient();
  const units = useUnitSystem();
  const announce = useAnnounce();
  const [days, setDays] = useState(30);
  const start = addDays(todayISO(), -(days - 1));
  const list = useQuery({ queryKey: ["exercise", start], queryFn: () => api.exercise(start) });
  const [editing, setEditing] = useState<Exercise | null>(null);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const del = useMutation({
    mutationFn: (x: Exercise) => api.deleteExercise(x.id),
    onSuccess: (_, x) => {
      invalidate(qc);
      announce(`Deleted ${x.name} on ${fmtShortDate(x.date)}.`);
      rescueFocus(() => listHeading.current);
    },
  });
  const rows = list.data ?? [];
  const byDay = new Map<string, Exercise[]>();
  for (const x of rows) byDay.set(x.date, [...(byDay.get(x.date) ?? []), x]);
  const totalKcal = rows.reduce((s, x) => s + x.kcal, 0);

  return (
    <div className="stack">
      <h1>Exercise</h1>
      <p className="muted">
        Each workout's energy above resting is added to that day's energy target, so your{" "}
        <Link to="/profile">activity level</Link> should describe everyday activity without the workouts you log here. Estimates use MET values from
        the{" "}
        <a href="https://pacompendium.com/adult-compendium/" target="_blank" rel="noopener noreferrer">
          2024 Adult Compendium of Physical Activities
          <NewTab />
        </a>{" "}
        and your latest weight; they can be off by 20% or more, so judge by your weight trend.
      </p>

      <section className="card stack" aria-labelledby="log-title">
        <h2 id="log-title">{editing ? "Edit workout" : "Log a workout"}</h2>
        <ExerciseForm units={units} editing={editing} onDone={() => setEditing(null)} />
      </section>

      <section className="card stack-sm" aria-labelledby="recent-title">
        <div className="row between wrap">
          <h2 id="recent-title" ref={listHeading}>
            Last {days} days
          </h2>
          {rows.length > 0 && (
            <span className="muted small">
              {rows.length} workout{rows.length === 1 ? "" : "s"} · {Math.round(totalKcal).toLocaleString()} kcal above resting
            </span>
          )}
        </div>
        <ErrorBox error={list.error || del.error} />
        {list.isLoading && <Loading />}
        {list.data && rows.length === 0 && <p className="muted">No workouts logged in this period.</p>}
        {[...byDay.entries()].map(([day, items]) => (
          <div key={day} className="meal-group">
            <h3 className="h-sm">{fmtShortDate(day)}</h3>
            <ul className="plain-list">
              {items.map((x) => (
                <li key={x.id} className="entry">
                  <div className="entry-main">
                    <div className="entry-text">
                      <strong>{x.name}</strong>{" "}
                      <span className="muted">
                        {[
                          fmtDuration(x.duration_min),
                          x.distance_m !== null && `${fmt1(toDistance(x.distance_m, units))} ${distanceUnit(units)}`,
                          x.avg_hr !== null && `${Math.round(x.avg_hr)} bpm`,
                          x.met !== null && `${x.met} MET`,
                          SOURCE_LABEL[x.source],
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </div>
                    <div className="entry-actions">
                      <span className="chip" title={x.calc_note}>
                        {x.kcal_method === "none" ? "0 kcal" : `+${Math.round(x.kcal)} kcal`} · {METHOD_LABEL[x.kcal_method]}
                      </span>
                      <button
                        type="button"
                        className="btn-link small"
                        onClick={() => {
                          setEditing(x);
                          rescueFocus(() => document.getElementById("exercise-date"));
                        }}
                      >
                        Edit<VisuallyHidden> {x.name}</VisuallyHidden>
                      </button>
                      <button type="button" className="btn-link small danger" disabled={del.isPending} onClick={() => del.mutate(x)}>
                        Delete<VisuallyHidden> {x.name}</VisuallyHidden>
                      </button>
                    </div>
                  </div>
                  <div className={`small ${x.kcal_method === "none" ? "warn-text" : "muted"}`}>{x.calc_note}</div>
                  {x.note && <div className="small">{x.note}</div>}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {list.data && days < 365 && (
          <div>
            <button type="button" className="btn btn-sm" onClick={() => setDays(days < 90 ? 90 : 365)}>
              Show {days < 90 ? "90 days" : "a year"}
            </button>
          </div>
        )}
      </section>

      <ImportSection />
    </div>
  );
}
