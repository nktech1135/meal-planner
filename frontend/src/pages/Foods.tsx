import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading, MacroLine } from "../components/common";
import { TrustBadge, TrustLegend, TRUST_INFO } from "../components/TrustBadge";
import { basisLabel, SOURCE_NAMES, useAppInfo } from "../lib";
import type { SearchHit, Source } from "../types";
import { Button, tabPanelProps, TabList, useAnnounceWhen, VisuallyHidden } from "../components/a11y";

const PAGE = 100;

function LocalSearch() {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [mine, setMine] = useState(false);
  const [kind, setKind] = useState("");
  const foods = useInfiniteQuery({
    queryKey: ["foods", "browse", submitted, mine, kind],
    queryFn: ({ pageParam }) => api.foods(submitted, { mine, kind: kind || undefined, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.length === PAGE ? pages.length * PAGE : undefined),
  });
  const list = foods.data?.pages.flat();
  const n = list?.length ?? 0;
  useAnnounceWhen(
    list && !foods.isFetching && (submitted || mine || kind)
      ? `${n === 0 ? "No" : foods.hasNextPage ? `${n} or more` : n} food${n === 1 ? "" : "s"} found${submitted ? ` for “${submitted}”` : ""}${kind ? `, ${kind === "food" ? "foods" : "supplements"} only` : ""}${mine ? ", yours only" : ""}.`
      : null,
  );
  return (
    <div className="stack">
      <form
        className="row wrap"
        role="search"
        aria-label="Your food database"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(q);
        }}
      >
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search foods and supplements…"
          aria-label="Search foods and supplements"
          className="grow"
        />
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
      {list?.length === 0 && (
        <p className="muted">No foods found. Import from an online source, or add one manually.</p>
      )}
      <ul className="plain-list cards">
        {list?.map((f) => (
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
      {foods.hasNextPage && (
        <div>
          <Button type="button" className="btn" onClick={() => foods.fetchNextPage()} disabled={foods.isFetchingNextPage}>
            {foods.isFetchingNextPage ? "Loading…" : "Show more"}
          </Button>
        </div>
      )}
    </div>
  );
}

function SourceCard({ s, selected, onSelect }: { s: Source; selected: boolean; onSelect: () => void }) {
  return (
    <Button
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
    </Button>
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
  const hitCount = hits.data?.length ?? 0;
  useAnnounceWhen(
    search && hits.data && !hits.isFetching
      ? `${hitCount === 0 ? "No" : hitCount} result${hitCount === 1 ? "" : "s"} from ${activeSource?.name ?? "the source"} for “${search.q}”.`
      : null,
  );
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
        <form className="row wrap" role="search" aria-label={activeSource.name} onSubmit={submit}>
          <input
            type="search"
            className="grow"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${activeSource.name}…`}
            aria-label={`Search ${activeSource.name}`}
            minLength={2}
          />
          <Button className="btn btn-primary" type="submit" disabled={q.trim().length < 2}>
            Search
          </Button>
        </form>
      )}
      {activeSource?.trust_level === "unverified" && (
        <div className="alert alert-warn">
          <strong>
            <span aria-hidden="true">⚠ </span>Unverified source.
          </strong> {TRUST_INFO.unverified.description} Anything imported from here stays flagged as unverified.
        </div>
      )}
      <ErrorBox error={hits.error || importer.error} />
      {hits.isFetching && <Loading what="Searching" />}
      {hits.data?.length === 0 && <p className="muted">No results.</p>}
      <ul className="plain-list cards">
        {hits.data?.map((h) => (
          <li key={`${h.source}-${h.source_id}`} className={`card ${h.trust_level === "unverified" ? "card-unverified" : ""}`}>
            <div className="row between">
              <h2 className="h-card">
                {h.name}
                {h.brand && <span className="muted"> · {h.brand}</span>}
              </h2>
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
                    Open<VisuallyHidden> {h.name}</VisuallyHidden>
                  </Link>
                  <Button type="button" className="btn-link" onClick={() => importer.mutate(h)} disabled={importer.isPending}>
                    Re-import (refresh)<VisuallyHidden> {h.name}</VisuallyHidden>
                  </Button>
                </>
              ) : (
                <Button type="button" className="btn" onClick={() => importer.mutate(h)} disabled={importer.isPending}>
                  {importer.isPending && importer.variables?.source_id === h.source_id ? "Importing…" : "Import"}
                  <VisuallyHidden> {h.name}</VisuallyHidden>
                </Button>
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
        <div className="row wrap">
          <Link to="/supplements/check" className="btn">
            Supplement check
          </Link>
          <Link to="/foods/new" className="btn btn-primary">
            + New food
          </Link>
        </div>
      </div>
      <TabList
        id="foods"
        label="Where to search"
        value={tab}
        onChange={(t) => setParams(t === "online" ? { tab: "online" } : {}, { replace: true })}
        tabs={[
          { value: "local", label: "My database" },
          { value: "online", label: "Online sources" },
        ]}
      />
      <div {...tabPanelProps("foods", tab)}>{tab === "local" ? <LocalSearch /> : <OnlineSearch />}</div>
      <TrustLegend />
    </div>
  );
}
