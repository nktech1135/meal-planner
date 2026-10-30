import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { FoodSummary } from "../types";
import { basisLabel } from "../lib";
import { BarcodeScanner } from "./BarcodeScanner";
import { MacroLine } from "./common";
import { TrustBadge } from "./TrustBadge";
import { useAnnounceWhen, useReturnFocus } from "./a11y";
import { useActingFor } from "./actingFor";

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
  // Planning for someone else: search as them, and leave out the barcode lookup, which imports foods
  // into your own list (they couldn't see them).
  const actingFor = useActingFor();
  const forUser = actingFor?.id ?? null;
  const [q, setQ] = useState("");
  const [scanning, setScanning] = useState(false);
  const dq = useDebounced(q);
  useEffect(() => {
    onQueryChange?.(dq.trim());
  }, [dq, onQueryChange]);
  const results = useQuery({
    queryKey: ["foods", dq, kind ?? "", forUser],
    queryFn: () => api.foods(dq, { kind, limit: 25, for_user: forUser }),
    enabled: dq.trim().length >= 1,
  });
  const items = (results.data ?? []).filter((f) => f.id !== excludeId);
  const scanButton = useReturnFocus<HTMLButtonElement>(scanning);
  // Say how many results there are once a search settles (typing alone gives no feedback otherwise).
  const settled = dq.trim() && results.data && !results.isFetching && dq === q;
  useAnnounceWhen(
    settled ? (items.length ? `${items.length === 25 ? "25 or more" : items.length} food${items.length === 1 ? "" : "s"} found for “${dq.trim()}”.` : `No foods found for “${dq.trim()}”.`) : null,
  );
  return (
    <div className="picker">
      <div className="picker-search">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label="Search foods" />
        {!actingFor && (
          <button ref={scanButton} type="button" className="btn btn-sm" aria-expanded={scanning} onClick={() => setScanning((s) => !s)}>
            Scan barcode
          </button>
        )}
      </div>
      {actingFor && (
        <p className="muted small">
          Showing the shared food database and {actingFor.name}'s own foods. Your private foods aren't offered, since {actingFor.name} couldn't see
          them.
        </p>
      )}
      {scanning && !actingFor && (
        <BarcodeScanner
          onClose={() => setScanning(false)}
          onPick={(f) => {
            setScanning(false);
            onPick(f);
          }}
        />
      )}
      {dq.trim() && beforeResults}
      {dq.trim() && (
        <ul className="pick-list" aria-label="Food database results">
          {results.isLoading && <li className="muted">Searching…</li>}
          {!results.isLoading && items.length === 0 && (
            <li className="muted">
              {actingFor
                ? `No matches among the shared foods or ${actingFor.name}'s own. ${actingFor.name} can add it under Foods.`
                : "No matches. Import from an online source or add it manually under Foods."}
            </li>
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
