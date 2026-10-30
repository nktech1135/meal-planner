import { Children, cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from "react";
import { errorMessage } from "../api";
import { ScrollRegion, useAnnounceText } from "./a11y";
import { fmtAmount, nutrientName, useNutrients } from "../lib";
import type { Component, EvaluationStatus, NutrientMap } from "../types";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      {errorMessage(error)}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted">{what}…</p>;
}

const CONTROLS = ["input", "select", "textarea"];

/**
 * A labelled form field. The first input/select/textarea child gets an id the <label> points at, and
 * the hint and error are linked with aria-describedby (an error also sets aria-invalid). Without a
 * form control (e.g. a notice in place of a select) it's a group named by the label.
 */
export function Field({ label, children, hint, error }: { label: ReactNode; children: ReactNode; hint?: ReactNode; error?: ReactNode }) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const kids = Children.toArray(children);
  const at = kids.findIndex((k) => isValidElement(k) && typeof k.type === "string" && CONTROLS.includes(k.type));
  const hintEl = hint ? (
    <span id={hintId} className="field-hint">
      {hint}
    </span>
  ) : null;
  const errorEl = error ? (
    <span id={errorId} className="field-error">
      {error}
    </span>
  ) : null;
  if (at === -1) {
    return (
      <div className="field" role="group" aria-labelledby={`${id}-label`} aria-describedby={[hint && hintId, error && errorId].filter(Boolean).join(" ") || undefined}>
        <span id={`${id}-label`} className="field-label">
          {label}
        </span>
        {children}
        {hintEl}
        {errorEl}
      </div>
    );
  }
  const control = kids[at] as ReactElement<Record<string, unknown>>;
  const controlId = (control.props.id as string | undefined) ?? id;
  const describedBy = [control.props["aria-describedby"], hint && hintId, error && errorId].filter(Boolean).join(" ") || undefined;
  kids[at] = cloneElement(control, {
    id: controlId,
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : control.props["aria-invalid"],
  });
  return (
    <div className="field">
      <label className="field-label" htmlFor={controlId}>
        {label}
      </label>
      {kids}
      {hintEl}
      {errorEl}
    </div>
  );
}

const MACRO_ORDER = ["energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugars_g"];
const MACRO_SHORT: Record<string, [string, string]> = {
  protein_g: ["P", "protein"],
  fat_g: ["F", "fat"],
  carbs_g: ["C", "carbs"],
  fiber_g: ["fiber", "fiber"],
  sugars_g: ["sugar", "sugar"],
};

/** "380 kcal · P 13 g · F 7 g …" on screen; "380 kcal, protein 13 g, fat 7 g …" for screen readers. */
export function MacroLine({ values }: { values: NutrientMap }) {
  const { byCode } = useNutrients();
  const codes = MACRO_ORDER.filter((c) => values[c] !== undefined);
  if (!codes.length) return <span className="muted">no macro data</span>;
  return (
    <span className="macros">
      {codes.map((c, i) => {
        const sep = i > 0 ? <span aria-hidden="true"> · </span> : null;
        if (c === "energy_kcal") {
          return (
            <span key={c}>
              {sep}
              {Math.round(values[c])} kcal
            </span>
          );
        }
        const [short, long] = MACRO_SHORT[c];
        return (
          <span key={c}>
            {sep}
            <span className="sr-only">, </span>
            {short === long ? short : <><span aria-hidden="true">{short}</span><span className="sr-only">{long}</span></>}{" "}
            {fmtAmount(values[c], byCode[c]?.unit ?? "")}
          </span>
        );
      })}
    </span>
  );
}

/** Full nutrient table in catalog order. Unknown codes go last. */
export function NutrientTable({
  values,
  derivations,
  emptyText = "No nutrient values.",
  caption,
}: {
  values: NutrientMap;
  derivations?: Record<string, string | null>;
  emptyText?: string;
  /** Read by screen readers before the table, e.g. "Nutrients per 100 g". */
  caption?: string;
}) {
  const { list, byCode } = useNutrients();
  const order = list.map((n) => n.code);
  const codes = Object.keys(values).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
  if (!codes.length) return <p className="muted">{emptyText}</p>;
  return (
    <ScrollRegion label={caption ?? "Nutrients"}>
      <table className="table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            <th scope="col">Nutrient</th>
            <th scope="col" className="num">
              Amount
            </th>
            {derivations && <th scope="col">Derivation</th>}
          </tr>
        </thead>
        <tbody>
          {codes.map((c) => (
            <tr key={c}>
              <th scope="row" className="th-plain">
                {nutrientName(byCode, c)}
              </th>
              <td className="num">{fmtAmount(values[c], byCode[c]?.unit)}</td>
              {derivations && <td className="muted">{derivations[c] ?? ""}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

export function ComponentList({
  items,
  title = "Other label components",
  level = 3,
}: {
  items: Component[];
  title?: string | null;
  level?: 2 | 3 | 4;
}) {
  if (!items?.length) return null;
  const H = `h${level}` as "h2" | "h3" | "h4";
  return (
    <section>
      {title && <H>{title}</H>}
      <ul className="plain-list">
        {items.map((c, i) => (
          <li key={`${c.name}-${i}`}>
            <strong>{c.name}</strong>
            {c.amount !== null && c.amount !== undefined ? ` — ${fmtAmount(c.amount, c.unit ?? "")}` : ""}
            {c.note ? <span className="muted"> ({c.note})</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Notes({ notes }: { notes: string[] }) {
  if (!notes?.length) return null;
  return (
    <ul className="notes">
      {notes.map((n, i) => (
        <li key={i}>{n}</li>
      ))}
    </ul>
  );
}

/**
 * Inline success/failure message; the icon and wording carry the status, not just colour. Its text is
 * announced when it appears or changes (politely for success, assertively for failure).
 */
export function ResultNote({ ok, children, id }: { ok: boolean; children: ReactNode; id?: string }) {
  const ref = useAnnounceText<HTMLDivElement>({ assertive: !ok });
  return (
    <div ref={ref} id={id} className={`result ${ok ? "result-ok" : "result-fail"}`}>
      <span aria-hidden="true">{ok ? "✓" : "✗"}</span> <span className="sr-only">{ok ? "Success:" : "Failed:"}</span> {children}
    </div>
  );
}

export const STATUS: Record<EvaluationStatus, { text: string; icon: string }> = {
  ok: { text: "OK", icon: "" },
  below: { text: "Below", icon: "" },
  above_max: { text: "Above limit", icon: "⚠ " },
  // Over a macronutrient range ceiling (e.g. protein above 35% of energy): worth knowing, not a safety limit.
  above_range: { text: "Above range", icon: "↑ " },
  partial: { text: "Partly counted", icon: "◐ " },
};

/** Target status as words (plus an icon for the ones that need attention), never colour alone. */
export function StatusPill({ status }: { status: EvaluationStatus }) {
  const s = STATUS[status] ?? STATUS.ok;
  return (
    <span className={`status-pill status-${status}`}>
      {s.icon && <span aria-hidden="true">{s.icon}</span>}
      {s.text}
    </span>
  );
}

/** A read-only value with a Copy button (reset/invite links). */
export function CopyField({ label, value, hint }: { label: string; value: string; hint?: ReactNode }) {
  const [copied, setCopied] = useState<boolean | null>(null);
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="row copy-field">
        <input readOnly value={value} aria-label={label} className="grow mono" onFocus={(e) => e.target.select()} />
        <button
          type="button"
          className="btn btn-sm"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          Copy
        </button>
      </div>
      <span className="field-hint" role="status">
        {copied === true ? "✓ Copied. " : copied === false ? "Couldn't copy automatically; select the text and copy it. " : ""}
        {hint}
      </span>
    </div>
  );
}
