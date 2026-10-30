import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading, MacroLine } from "../components/common";
import { TrustBadge, TrustLegend, TRUST_INFO } from "../components/TrustBadge";
import { basisLabel, SOURCE_NAMES, useAppInfo } from "../lib";
import type { SearchHit, Source } from "../types";

function LocalSearch() {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [mine, setMine] = useState(false);
  const [kind, setKind] = useState("");
  const foods = useQuery({
    queryKey: ["foods", "browse", submitted, mine, kind],
    queryFn: () => api.foods(submitted, { mine, kind: kind || undefined, limit: 100 }),
  });
  return (
    <div className="stack">
      <form
        className="row wrap"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(q);
        }}
      >
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search foods and supplements…" aria-label="Search" className="grow" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
          <option value="">All kinds</option>
          <option value="food">Foods</option>
          <option value="supplement">Supplements</option>
        </select>
        <label className="checkbox">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only mine
        </label>
        <button className="btn" type="submit">
          Search
        </button>
      </form>
      <ErrorBox error={foods.error} />
      {foods.isLoading && <Loading />}
      {foods.data?.length === 0 && (
        <p className="muted">No foods found. Import from an online source, or add one manually.</p>
      )}
      <ul className="plain-list cards">
        {foods.data?.map((f) => (
          <li key={f.id} className={`card card-link ${f.trust_level === "unverified" ? "card-unverified" : ""}`}>
            <Link to={`/foods/${f.id}`}>
              <div className="row between">
                <strong>
                  {f.name}
                  {f.brand && <span className="muted"> · {f.brand}</span>}
                </strong>
                <TrustBadge level={f.trust_level} />
              </div>
              <div className="row small muted wrap">
                <span>{SOURCE_NAMES[f.source] ?? f.source}</span>
                {f.source_data_type && <span>{f.source_data_type}</span>}
                {f.category && <span className="food-category">{f.category}</span>}
                {f.state && <span className="chip">{f.state}</span>}
                {f.kind === "supplement" && <span className="chip">supplement</span>}
                <span>{basisLabel(f)}</span>
              </div>
              <MacroLine values={f.macros} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SourceCard({ s, selected, onSelect }: { s: Source; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={`card source-card ${selected ? "selected" : ""} ${s.trust_level === "unverified" ? "card-unverified" : ""}`}
      onClick={onSelect}
      disabled={!s.enabled}
      aria-pressed={selected}
    >
      <div className="row between">
        <strong>{s.name}</strong>
        <TrustBadge level={s.trust_level} />
      </div>
      <p className="small">{s.description}</p>
      <div className="row small wrap">
        <span className="chip">{s.paid ? "Paid / licensed" : "Free"}</span>
        {s.enabled ? <span className="chip chip-ok">Enabled</span> : <span className="chip chip-off">Disabled</span>}
      </div>
      {!s.enabled && s.disabled_reason && <p className="muted small">{s.disabled_reason}</p>}
    </button>
  );
}

function UsdaDemoNotice() {
  const { user } = useAuth();
  return (
    <div className="alert alert-info">
      USDA searches use a shared, heavily rate-limited demo key, so they may fail at busy times.{" "}
      {user?.is_admin ? (
        <>
          <Link to="/settings">Add a free USDA key in Settings</Link>.
        </>
      ) : (
        "Ask an admin to add a free USDA key."
      )}
    </div>
  );
}

function OnlineSearch() {
  const navigate = useNavigate();
  const info = useAppInfo();
  const qc = useQueryClient();
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const [key, setKey] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState<{ key: string; q: string } | null>(null);
  const active = key ?? sources.data?.find((s) => s.enabled)?.key ?? null;
  const activeSource = sources.data?.find((s) => s.key === active);

  const hits = useQuery({
    queryKey: ["source-search", search],
    queryFn: () => api.searchSource(search!.key, search!.q),
    enabled: !!search,
    retry: false,
  });
  const importer = useMutation({
    mutationFn: (h: SearchHit) => api.importFood(h.source, h.source_id, h.name),
    onSuccess: (food) => {
      qc.invalidateQueries({ queryKey: ["foods"] });
      navigate(`/foods/${food.id}`);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (active && q.trim().length >= 2) setSearch({ key: active, q: q.trim() });
  }

  return (
    <div className="stack">
      <ErrorBox error={sources.error} />
      <div className="source-grid">
        {sources.data?.map((s) => (
          <SourceCard key={s.key} s={s} selected={s.key === active} onSelect={() => setKey(s.key)} />
        ))}
      </div>
      {activeSource?.key === "usda_fdc" && info?.usda_demo_key && <UsdaDemoNotice />}
      {activeSource && (
        <form className="row wrap" onSubmit={submit}>
          <input
            type="search"
            className="grow"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${activeSource.name}…`}
            aria-label={`Search ${activeSource.name}`}
            minLength={2}
          />
          <button className="btn btn-primary" type="submit" disabled={q.trim().length < 2}>
            Search
          </button>
        </form>
      )}
      {activeSource?.trust_level === "unverified" && (
        <div className="alert alert-warn">
          <strong>⚠ Unverified source.</strong> {TRUST_INFO.unverified.description} Anything imported from here stays flagged as unverified.
        </div>
      )}
      <ErrorBox error={hits.error || importer.error} />
      {hits.isFetching && <Loading what="Searching" />}
      {hits.data?.length === 0 && <p className="muted">No results.</p>}
      <ul className="plain-list cards">
        {hits.data?.map((h) => (
          <li key={`${h.source}-${h.source_id}`} className={`card ${h.trust_level === "unverified" ? "card-unverified" : ""}`}>
            <div className="row between">
              <strong>
                {h.name}
                {h.brand && <span className="muted"> · {h.brand}</span>}
              </strong>
              <TrustBadge level={h.trust_level} />
            </div>
            <div className="row small muted wrap">
              {h.data_type && <span>{h.data_type}</span>}
              {h.detail && <span>{h.detail}</span>}
              {h.kind === "supplement" && <span className="chip">supplement</span>}
              <span>{h.basis === "100g" ? "per 100 g" : "per serving"}</span>
            </div>
            {Object.keys(h.summary).length > 0 && <MacroLine values={h.summary} />}
            <div className="row">
              {h.imported_food_id ? (
                <>
                  <Link className="btn" to={`/foods/${h.imported_food_id}`}>
                    Open
                  </Link>
                  <button type="button" className="btn-link" onClick={() => importer.mutate(h)} disabled={importer.isPending}>
                    Re-import (refresh)
                  </button>
                </>
              ) : (
                <button type="button" className="btn" onClick={() => importer.mutate(h)} disabled={importer.isPending}>
                  {importer.isPending && importer.variables?.source_id === h.source_id ? "Importing…" : "Import"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function FoodsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "online" ? "online" : "local";
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Foods</h1>
        <Link to="/foods/new" className="btn btn-primary">
          + New food
        </Link>
      </div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "local"} className={tab === "local" ? "active" : ""} onClick={() => setParams({})}>
          My database
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "online"}
          className={tab === "online" ? "active" : ""}
          onClick={() => setParams({ tab: "online" })}
        >
          Online sources
        </button>
      </div>
      {tab === "local" ? <LocalSearch /> : <OnlineSearch />}
      <TrustLegend />
    </div>
  );
}
