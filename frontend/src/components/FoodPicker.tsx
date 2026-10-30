import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { FoodSummary } from "../types";
import { basisLabel } from "../lib";
import { MacroLine } from "./common";
import { TrustBadge } from "./TrustBadge";

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Search the local food database and pick one result. */
export function FoodPicker({
  onPick,
  kind,
  placeholder = "Search your food database…",
  excludeId,
  onQueryChange,
  beforeResults,
}: {
  onPick: (f: FoodSummary) => void;
  kind?: "food" | "supplement";
  placeholder?: string;
  excludeId?: number;
  /** Called with the debounced search text. */
  onQueryChange?: (q: string) => void;
  /** Shown between the search box and the database results while searching. */
  beforeResults?: ReactNode;
}) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  useEffect(() => {
    onQueryChange?.(dq.trim());
  }, [dq, onQueryChange]);
  const results = useQuery({
    queryKey: ["foods", dq, kind ?? ""],
    queryFn: () => api.foods(dq, { kind, limit: 25 }),
    enabled: dq.trim().length >= 1,
  });
  const items = (results.data ?? []).filter((f) => f.id !== excludeId);
  return (
    <div className="picker">
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label="Search foods" />
      {dq.trim() && beforeResults}
      {dq.trim() && (
        <ul className="pick-list" aria-label="Food database results">
          {results.isLoading && <li className="muted">Searching…</li>}
          {!results.isLoading && items.length === 0 && (
            <li className="muted">No matches. Import from an online source or add it manually under Foods.</li>
          )}
          {items.map((f) => (
            <li key={f.id}>
              <button type="button" className="pick-item" onClick={() => onPick(f)}>
                <span className="pick-name">
                  {f.name}
                  {f.brand ? <span className="muted"> · {f.brand}</span> : null}
                </span>
                <span className="pick-meta">
                  <TrustBadge level={f.trust_level} />
                  {f.state && <span className="chip">{f.state}</span>}
                  {f.kind === "supplement" && <span className="chip">supplement</span>}
                  <span className="muted small">{basisLabel(f)}</span>
                  {f.category && <span className="muted small food-category">{f.category}</span>}
                </span>
                <MacroLine values={f.macros} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
