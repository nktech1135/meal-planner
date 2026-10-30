import type { ReactNode } from "react";
import { errorMessage } from "../api";
import { fmtAmount, nutrientName, useNutrients } from "../lib";
import type { Component, NutrientMap } from "../types";

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

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

const MACRO_ORDER = ["energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugars_g"];

export function MacroLine({ values }: { values: NutrientMap }) {
  const { byCode } = useNutrients();
  const parts = MACRO_ORDER.filter((c) => values[c] !== undefined).map((c) => {
    const short: Record<string, string> = {
      energy_kcal: "kcal",
      protein_g: "P",
      fat_g: "F",
      carbs_g: "C",
      fiber_g: "fiber",
      sugars_g: "sugar",
    };
    const unit = byCode[c]?.unit ?? "";
    return c === "energy_kcal" ? `${Math.round(values[c])} kcal` : `${short[c]} ${fmtAmount(values[c], unit)}`;
  });
  if (!parts.length) return <span className="muted">no macro data</span>;
  return <span className="macros">{parts.join(" · ")}</span>;
}

/** Full nutrient table in catalog order. Unknown codes go last. */
export function NutrientTable({
  values,
  derivations,
  emptyText = "No nutrient values.",
}: {
  values: NutrientMap;
  derivations?: Record<string, string | null>;
  emptyText?: string;
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
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Nutrient</th>
            <th className="num">Amount</th>
            {derivations && <th>Derivation</th>}
          </tr>
        </thead>
        <tbody>
          {codes.map((c) => (
            <tr key={c}>
              <td>{nutrientName(byCode, c)}</td>
              <td className="num">{fmtAmount(values[c], byCode[c]?.unit)}</td>
              {derivations && <td className="muted">{derivations[c] ?? ""}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComponentList({ items, title = "Other label components" }: { items: Component[]; title?: string | null }) {
  if (!items?.length) return null;
  return (
    <section>
      {title && <h3>{title}</h3>}
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

/** Inline success/failure message; the icon and wording carry the status, not just colour. */
export function ResultNote({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <div className={`result ${ok ? "result-ok" : "result-fail"}`} role="status">
      <span aria-hidden="true">{ok ? "✓" : "✗"}</span> <span className="sr-only">{ok ? "Success:" : "Failed:"}</span> {children}
    </div>
  );
}
