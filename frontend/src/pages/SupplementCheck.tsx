import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, Loading, Notes } from "../components/common";
import { FoodPicker } from "../components/FoodPicker";
import { TrustBadge, TRUST_INFO } from "../components/TrustBadge";
import { basisLabel, fmtAmount, fmtNum, fmtShortDate, parseNum, SOURCE_NAMES, useAppInfo } from "../lib";
import type { CheckNutrient, Food, CheckStatus, SearchHit, StackItem, SupplementCheck, SupplementVerdict, VerdictCode } from "../types";
import { Button, focusElement, focusSoon, NewTab, ScrollRegion, useAnnounce, useAnnounceWhen, VisuallyHidden } from "../components/a11y";

/*
 * Supplement check: would a product add anything that food and other supplements don't already provide?
 * The checked state lives in the URL (?food=&servings=&days=), so reloads, links and Back all work.
 */

const PERIODS = [7, 14, 30, 90];
const DEFAULT_DAYS = 14;

export const VERDICT: Record<VerdictCode, { label: string; icon: string }> = {
  useful: { label: "Fills gaps", icon: "+" },
  partly_useful: { label: "Partly useful", icon: "◐" },
  not_needed: { label: "Probably not needed", icon: "○" },
  caution: { label: "Over an upper limit", icon: "⚠" },
  unclear: { label: "Can't tell", icon: "?" },
  unknown: { label: "Needs your profile", icon: "?" },
};

/** Verdict in words (with a decorative icon), never colour alone. */
export function VerdictChip({ code }: { code: VerdictCode }) {
  const v = VERDICT[code] ?? VERDICT.unclear;
  return (
    <span className={`verdict-chip verdict-${code}`}>
      <span aria-hidden="true">{v.icon} </span>
      {v.label}
    </span>
  );
}

const STATUS_TEXT: Record<CheckStatus, { text: string; icon: string }> = {
  over_limit: { text: "Over the upper limit", icon: "⚠ " },
  closes_gap: { text: "Closes the gap", icon: "+ " },
  narrows_gap: { text: "Narrows the gap", icon: "+ " },
  partial: { text: "Not counted yet", icon: "◐ " },
  covered_by_supplements: { text: "Covered by your other supplements", icon: "" },
  covered_by_food: { text: "Already covered by food", icon: "" },
  minor: { text: "Too little to matter", icon: "" },
  no_reference: { text: "No reference intake", icon: "" },
  info: { text: "Not judged", icon: "" },
};

const GROUPS: { title: string; statuses: CheckStatus[] }[] = [
  { title: "Over the upper limit", statuses: ["over_limit"] },
  { title: "Fills a gap", statuses: ["closes_gap", "narrows_gap"] },
  { title: "Not counted yet", statuses: ["partial"] },
  { title: "Already covered", statuses: ["covered_by_supplements", "covered_by_food"] },
  { title: "Too little to matter", statuses: ["minor"] },
  { title: "Not judged", statuses: ["no_reference", "info"] },
];

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

function servingsText(n: number | null | undefined, label?: string) {
  if (!n) return "";
  return `${plural(n, "serving")}${label ? ` (${label} each)` : ""} a day`;
}

/** One serving in words, as the check counts it (mirrors the server's serving label). */
function servingLabel(f: Pick<Food, "basis" | "serving_quantity" | "serving_unit" | "serving_size_g">) {
  if (f.basis !== "100g" && f.serving_quantity && f.serving_unit) return `${fmtNum(f.serving_quantity)} ${f.serving_unit}`;
  if (f.serving_size_g) return `${fmtNum(f.serving_size_g)} g`;
  return "1 serving";
}

function dateRange(start: string, end: string) {
  return start === end ? fmtShortDate(start) : `${fmtShortDate(start)} – ${fmtShortDate(end)}`;
}

/** An amount, or a dash read as "none" for zero. */
function Amount({ value, unit }: { value: number | null | undefined; unit: string }) {
  if (value === null || value === undefined || value === 0) {
    return (
      <>
        <span aria-hidden="true">–</span>
        <VisuallyHidden>none</VisuallyHidden>
      </>
    );
  }
  return <>{fmtAmount(value, unit)}</>;
}

// ---------------------------------------------------------------------------------------------
// Your supplements

function StackList({ days, onDetails }: { days: number; onDetails: (item: StackItem) => void }) {
  const stack = useQuery({ queryKey: ["supplement-stack", days], queryFn: () => api.supplementStack(days), placeholderData: (prev) => prev });
  const s = stack.data;
  const stale = stack.isPlaceholderData && stack.isFetching;
  return (
    <section className="card stack" aria-labelledby="stack-title">
      <h2 id="stack-title">Your supplements</h2>
      <ErrorBox error={stack.error} />
      {stack.isLoading && <Loading />}
      {s && s.items.length === 0 && (
        <div className="stack-sm">
          <p className="muted">
            No supplements logged in the last {days} days. Supplements you log in that period appear here, each checked against your food and your
            other supplements.
          </p>
          <p className="small">
            <Link to="/log">Log a supplement</Link>, or check a product below before you buy it.
          </p>
        </div>
      )}
      {s && s.items.length > 0 && (
        <div className={`stack-sm ${stale ? "is-stale" : ""}`} aria-busy={stale}>
          <p className="muted small">
            Each one is compared with your food and the rest of your supplements over {plural(s.window.logged_days, "logged day")} (
            {dateRange(s.window.start, s.window.end)}).
          </p>
          <ul className="plain-list stack-items">
            {s.items.map((it) => (
              <li key={`${it.food_id ?? ""}-${it.label}`} className="stack-item">
                <div className="stack-item-main">
                  <div className="row wrap">
                    <h3 className="h-card">
                      {it.label}
                      {it.brand && <span className="muted"> · {it.brand}</span>}
                    </h3>
                    {it.verdict && <VerdictChip code={it.verdict.code} />}
                  </div>
                  {it.verdict && <p className="stack-headline">{it.verdict.headline}</p>}
                  {it.error && <p className="small warn-text">{it.error}</p>}
                  <p className="muted small">
                    Taken on {it.days_taken} of {plural(s.window.logged_days, "logged day")}
                    {it.servings_per_day ? ` · usually ${servingsText(it.servings_per_day)}` : ""}
                    {it.verdict?.confidence === "low" ? " · low confidence" : ""}
                  </p>
                </div>
                {it.food_id && !it.error && (
                  <Button type="button" className="btn btn-sm" onClick={() => onDetails(it)}>
                    Details<VisuallyHidden> for {it.label}</VisuallyHidden>
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// Online label databases (NIH DSLD and the other enabled sources): import, then check.

function OnlineSearch({ onChoose }: { onChoose: (id: number, name: string) => void }) {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const enabled = (sources.data ?? []).filter((s) => s.enabled);
  const [key, setKey] = useState<string | null>(null);
  const active = key ?? (enabled.find((s) => s.key === "nih_dsld") ?? enabled[0])?.key ?? null;
  const activeSource = enabled.find((s) => s.key === active);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState<{ key: string; q: string } | null>(null);
  const hits = useQuery({
    queryKey: ["source-search", search],
    queryFn: () => api.searchSource(search!.key, search!.q),
    enabled: !!search,
    retry: false,
  });
  const n = hits.data?.length ?? 0;
  useAnnounceWhen(
    search && hits.data && !hits.isFetching ? `${n === 0 ? "No" : n} result${n === 1 ? "" : "s"} from ${activeSource?.name ?? "the source"} for “${search.q}”.` : null,
  );
  const importer = useMutation({
    mutationFn: async (h: SearchHit) => (h.imported_food_id ? { id: h.imported_food_id, name: h.name } : api.importFood(h.source, h.source_id, h.name)),
    onSuccess: (f) => onChoose(f.id, f.name),
  });
  const go = () => {
    if (active && q.trim().length >= 2) setSearch({ key: active, q: q.trim() });
  };

  if (sources.data && !enabled.length) return <p className="muted small">No online sources are switched on.</p>;
  return (
    <div className="stack-sm">
      {/* Not a <form>: this sits inside the check form. */}
      <div className="row wrap" role="search" aria-label="Online label databases">
        {enabled.length > 1 && (
          <select value={active ?? ""} onChange={(e) => setKey(e.target.value)} aria-label="Online source">
            {enabled.map((s) => (
              <option key={s.key} value={s.key}>
                {s.name}
              </option>
            ))}
          </select>
        )}
        <input
          type="search"
          className="grow"
          value={q}
          minLength={2}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              go();
            }
          }}
          placeholder={activeSource ? `Search ${activeSource.name}…` : "Search…"}
          aria-label={activeSource ? `Search ${activeSource.name}` : "Search online"}
        />
        <Button type="button" className="btn" onClick={go} disabled={q.trim().length < 2}>
          Search
        </Button>
      </div>
      {activeSource?.trust_level === "unverified" && (
        <p className="small warn-text">
          <span aria-hidden="true">⚠ </span>
          {TRUST_INFO.unverified.description}
        </p>
      )}
      <ErrorBox error={hits.error || importer.error} />
      {hits.isFetching && <Loading what="Searching" />}
      {hits.data && hits.data.length > 0 && (
        <ul className="pick-list" aria-label={`Results from ${activeSource?.name ?? "the source"}`}>
          {hits.data.map((h) => (
            <li key={`${h.source}-${h.source_id}`} className="online-hit">
              <span className="min-0">
                <span className="pick-name">
                  {h.name}
                  {h.brand && <span className="muted"> · {h.brand}</span>}
                </span>
                <span className="row wrap small">
                  <TrustBadge level={h.trust_level} />
                  {h.kind === "supplement" && <span className="chip">supplement</span>}
                  {h.detail && <span className="muted">{h.detail}</span>}
                </span>
              </span>
              <Button type="button" className="btn btn-sm" disabled={importer.isPending} onClick={() => importer.mutate(h)}>
                {importer.isPending && importer.variables?.source_id === h.source_id ? "Importing…" : h.imported_food_id ? "Choose" : "Import and choose"}
                <VisuallyHidden> {h.name}</VisuallyHidden>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Result

function StatusCell({ r, foodId }: { r: CheckNutrient; foodId: number }) {
  const s = STATUS_TEXT[r.status];
  const covered = r.status === "covered_by_supplements" && r.also_in.length > 0;
  return (
    <>
      <span className={`check-pill check-${r.status}`}>
        {s.icon && <span aria-hidden="true">{s.icon}</span>}
        {s.text}
        {covered && ` (${r.also_in.join(", ")})`}
      </span>
      {r.uncertain && (
        <span className="check-uncertain">
          <span aria-hidden="true">≈ </span>Uncertain
        </span>
      )}
      {r.uncounted.length > 0 && (
        <ul className="plain-list small uncounted">
          {r.uncounted.map((u, i) => (
            <li key={i}>
              <span className="uncounted-text">
                +{fmtAmount(u.amount, u.unit ?? "")} from {u.name} not counted.
              </span>{" "}
              {u.resolvable ? (
                <Link to={`/foods/${foodId}#forms`}>
                  Choose the form<VisuallyHidden> of {u.name}</VisuallyHidden>
                </Link>
              ) : (
                <span className="muted">Can't be converted.</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {r.status !== "covered_by_supplements" && r.also_in.length > 0 && (
        <span className="muted small block">Also in: {r.also_in.join(", ")}</span>
      )}
      <Notes notes={r.notes} />
    </>
  );
}

/** Column label shown inside each cell on phones, where the table is stacked into cards. */
const PhoneLabel = ({ children }: { children: ReactNode }) => <span className="cell-label">{children}</span>;

function NutrientRows({ r, foodId }: { r: CheckNutrient; foodId: number }) {
  const supplemental = r.ul_scope === "supplemental" && r.upper_limit !== null;
  return (
    <tr className={`check-row check-row-${r.status}`}>
      <th scope="row" className="check-name">
        {r.name}
      </th>
      <td className="check-status">
        <StatusCell r={r} foodId={foodId} />
      </td>
      <td className="num">
        <PhoneLabel>This product</PhoneLabel>
        <Amount value={r.product} unit={r.unit} />
        {r.product_share_of_reference !== null && r.product > 0 && (
          <span className="muted small block">{Math.round(r.product_share_of_reference * 100)}% of reference</span>
        )}
      </td>
      <td className="num">
        <PhoneLabel>Food</PhoneLabel>
        <Amount value={r.food} unit={r.unit} />
        {r.food_data_coverage !== null && r.food_data_coverage < 0.7 && (
          <span className="muted small block">reported for {Math.round(r.food_data_coverage * 100)}% of food</span>
        )}
      </td>
      <td className="num">
        <PhoneLabel>Other supplements</PhoneLabel>
        <Amount value={r.other_supplements} unit={r.unit} />
      </td>
      <td className="num">
        <PhoneLabel>Total with product</PhoneLabel>
        <Amount value={r.total_with} unit={r.unit} />
      </td>
      <td className="num">
        <PhoneLabel>Reference intake</PhoneLabel>
        {r.reference !== null ? (
          <>
            {fmtAmount(r.reference, r.unit)}
            {r.reference_kind && <span className="muted small block">{r.reference_kind}</span>}
          </>
        ) : (
          <Amount value={null} unit={r.unit} />
        )}
      </td>
      <td className="num">
        <PhoneLabel>Upper limit</PhoneLabel>
        {r.upper_limit !== null ? (
          <>
            {fmtAmount(r.upper_limit, r.unit)}
            {supplemental && r.limit_amount_with !== null && (
              <span className={`small block ${r.status === "over_limit" ? "danger-text" : "muted"}`}>
                supplements only: {fmtAmount(r.limit_amount_with, r.unit)} with this product
              </span>
            )}
          </>
        ) : (
          <Amount value={null} unit={r.unit} />
        )}
      </td>
    </tr>
  );
}

function NutrientTable({ result }: { result: SupplementCheck }) {
  const p = result.product;
  if (!result.nutrients.length) return <p className="muted">This product lists no nutrients with amounts.</p>;
  return (
    <ScrollRegion label="Nutrients compared" className="table-wrap check-table-wrap">
      <table className="table check-table">
        <caption className="sr-only">
          Nutrients in {p.name} at {servingsText(p.servings_per_day)}, compared with your average daily intake. Grouped by result.
        </caption>
        <thead>
          <tr>
            <th scope="col">Nutrient</th>
            <th scope="col">Result</th>
            <th scope="col" className="num">
              This product
            </th>
            <th scope="col" className="num">
              Food
            </th>
            <th scope="col" className="num">
              Other supplements
            </th>
            <th scope="col" className="num">
              Total with product
            </th>
            <th scope="col" className="num">
              Reference intake
            </th>
            <th scope="col" className="num">
              Upper limit
            </th>
          </tr>
        </thead>
        {GROUPS.map((g) => {
          const rows = result.nutrients.filter((r) => g.statuses.includes(r.status));
          if (!rows.length) return null;
          return (
            <tbody key={g.title}>
              <tr className="check-group">
                <th scope="rowgroup" colSpan={8}>
                  {g.title} <span className="muted">({rows.length})</span>
                </th>
              </tr>
              {rows.map((r) => (
                <NutrientRows key={r.code} r={r} foodId={p.food_id} />
              ))}
            </tbody>
          );
        })}
      </table>
    </ScrollRegion>
  );
}

function VerdictBanner({ v }: { v: SupplementVerdict }) {
  return (
    <div className={`verdict verdict-box-${v.code}`}>
      <p className="verdict-head">
        <VerdictChip code={v.code} />
        <strong className="verdict-headline">{v.headline}</strong>
      </p>
      {v.details.length > 0 && (
        <ul className="verdict-details">
          {v.details.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      {v.confidence === "low" ? (
        <div className="verdict-confidence">
          <strong>Low confidence.</strong>
          <ul>
            {v.confidence_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted small verdict-confidence">Confidence: normal.</p>
      )}
    </div>
  );
}

function AskAdvisor({ result, days }: { result: SupplementCheck; days: number }) {
  const info = useAppInfo();
  const { user } = useAuth();
  const p = result.product;
  if (!info) return null;
  if (!info.advisor_configured) {
    return (
      <p className="muted small">
        The advisor could summarise the evidence for this product, but it isn't set up yet (it needs an Anthropic API key).{" "}
        {user?.is_admin ? <Link to="/settings">Add one in Settings</Link> : "Ask an admin to add one in Settings."}
      </p>
    );
  }
  const dose = `${plural(p.servings_per_day, "serving")} (${p.serving_label} each)`;
  const message = `Is ${p.name}${p.brand ? ` by ${p.brand}` : ""} (food id ${p.food_id}) worth taking at ${dose} a day? Please check it against my intake over the last ${days} days and my other supplements.`;
  return (
    <div className="row wrap">
      <Link className="btn" to={`/advisor?ask=${encodeURIComponent(message)}`}>
        Ask the advisor about this
      </Link>
      <span className="muted small">Opens the advisor with a question filled in; nothing is sent until you press Send.</span>
    </div>
  );
}

function ResultView({ result, days }: { result: SupplementCheck; days: number }) {
  const p = result.product;
  const w = result.window;
  const lowEnergy = w.energy_target_kcal && w.avg_energy_kcal < w.energy_target_kcal * 0.6;
  return (
    <>
      <p className="muted">
        {p.brand && <>{p.brand} · </>}
        {servingsText(p.servings_per_day, p.serving_label)}.{" "}
        {result.already_taking ? (
          <>
            You logged it on {plural(result.already_taking.days_taken, "day")}
            {result.already_taking.servings_per_day ? `, usually ${servingsText(result.already_taking.servings_per_day)}` : ""}; it's compared with
            your intake without it.
          </>
        ) : (
          "You haven't logged it in this period."
        )}
      </p>

      <VerdictBanner v={result.verdict} />
      <AskAdvisor result={result} days={days} />

      {result.warnings.length > 0 && (
        <div className="alert alert-warn">
          <strong>About your reference intakes</strong>
          <ul>
            {result.warnings.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="stack-sm" aria-labelledby="check-nutrients-title">
        <h3 id="check-nutrients-title">Nutrients</h3>
        <p className="muted small">
          Average a day over your logged days. Where an upper limit applies to supplements only (as for magnesium or folic acid), it's compared with
          what you take from supplements, not food.
        </p>
        <NutrientTable result={result} />
      </section>

      {result.other_ingredients.length > 0 && (
        <section className="stack-sm" aria-labelledby="check-other-title">
          <h3 id="check-other-title">Other ingredients</h3>
          <p className="muted small">These have no reference intake, so whether you need them can't be judged from your intake.</p>
          <ul className="plain-list other-ingredients">
            {result.other_ingredients.map((c, i) => (
              <li key={`${c.name}-${i}`} className={c.also_in.length ? "is-duplicate" : ""}>
                <strong>{c.name}</strong>
                {c.amount !== null && <> — {fmtAmount(c.amount, c.unit ?? "")}</>}
                {c.also_in.length > 0 && (
                  <span className="chip chip-warn">
                    <span aria-hidden="true">↔ </span>
                    Also in: {c.also_in.map((a) => `${a.label} (${fmtAmount(a.amount, a.unit ?? "")})`).join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid-2 check-facts">
        <section className="stack-sm" aria-labelledby="check-window-title">
          <h3 id="check-window-title">What it was compared with</h3>
          <dl className="kv small">
            <dt>Period</dt>
            <dd>
              {dateRange(w.start, w.end)}
              {w.start === w.end ? " (nothing logged before today, so today only)" : ""}
            </dd>
            <dt>Logged days</dt>
            <dd>{w.logged_days}</dd>
            <dt>Food energy</dt>
            <dd>
              {fmtNum(w.avg_energy_kcal)} kcal a day on average
              {w.energy_target_kcal ? `, estimated need ${fmtNum(w.energy_target_kcal)} kcal` : ""}
              {lowEnergy ? " (some meals were probably not logged)" : ""}
            </dd>
            <dt>Other supplements</dt>
            <dd>
              {result.other_supplements.length
                ? result.other_supplements.map((s) => `${s.label} (${plural(s.days_taken, "day")})`).join(", ")
                : "none logged"}
            </dd>
          </dl>
        </section>
        <section className="stack-sm" aria-labelledby="check-source-title">
          <h3 id="check-source-title">About the product data</h3>
          <dl className="kv small">
            <dt>Trust</dt>
            <dd>
              <TrustBadge level={p.trust_level} />
              {p.result_trust_level !== p.trust_level && (
                <>
                  {" "}
                  this dose counts as <TrustBadge level={p.result_trust_level} />
                </>
              )}
            </dd>
            <dt>Source</dt>
            <dd>{SOURCE_NAMES[p.source] ?? p.source}</dd>
            {p.citation && (
              <>
                <dt>Citation</dt>
                <dd>{p.citation}</dd>
              </>
            )}
            {p.source_url && (
              <>
                <dt>Record</dt>
                <dd>
                  <a href={p.source_url} target="_blank" rel="noopener noreferrer">
                    View at source
                    <NewTab />
                  </a>
                </dd>
              </>
            )}
          </dl>
          <Notes notes={p.notes} />
          <p className="small">
            <Link to={`/foods/${p.food_id}`}>
              Open the product page<VisuallyHidden> for {p.name}</VisuallyHidden>
            </Link>
          </p>
        </section>
      </div>

      <section className="alert alert-info stack-sm" aria-labelledby="check-caveats-title">
        <h3 id="check-caveats-title" className="h-card">
          Keep in mind
        </h3>
        <ul>
          {result.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
          <li>This is a comparison of amounts, not medical advice.</li>
        </ul>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------------------------

type After = "focus" | "announce" | null;

export default function SupplementCheckPage() {
  const [params, setParams] = useSearchParams();
  const foodId = Number(params.get("food")) || null;
  const servingsParam = params.get("servings") ?? "";
  const servingsNum = parseNum(servingsParam);
  const servings = servingsNum !== null && servingsNum > 0 && servingsNum <= 100 ? servingsNum : null;
  const days = PERIODS.includes(Number(params.get("days"))) ? Number(params.get("days")) : DEFAULT_DAYS;

  // The form: what's chosen and typed, not yet checked. It follows the URL (Back, links from other pages).
  const [selectedId, setSelectedId] = useState<number | null>(foodId);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [servingsInput, setServingsInput] = useState(servingsParam);
  const [servingsError, setServingsError] = useState<string | null>(null);
  useEffect(() => {
    setSelectedId(foodId);
    setServingsInput(servingsParam);
    setServingsError(null);
  }, [foodId, servingsParam]);

  const selected = useQuery({ queryKey: ["food", selectedId], queryFn: () => api.food(selectedId!), enabled: !!selectedId });
  const check = useQuery({
    queryKey: ["supplement-check", foodId, servings, days],
    queryFn: () => api.checkSupplement({ food_id: foodId!, servings_per_day: servings, days }),
    enabled: !!foodId,
    retry: false,
    // Keep the previous result on screen while another period or dose for the same product loads.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === foodId ? prev : undefined),
  });

  const selectedRef = useRef<HTMLDivElement>(null);
  const servingsRef = useRef<HTMLInputElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const after = useRef<After>(null);
  const announce = useAnnounce();

  // After a check the user asked for: move focus to the result heading (or just announce, for a period change).
  useEffect(() => {
    if (!after.current || check.isFetching) return;
    if (!check.data && !check.error) return;
    if (after.current === "focus") {
      const el = resultHeading.current;
      if (el) {
        el.scrollIntoView({ block: "start" });
        focusElement(el, { preventScroll: true });
      }
    }
    if (check.data) announce(`${check.data.product.name}: ${check.data.verdict.headline}`);
    after.current = null;
  }, [check.data, check.error, check.isFetching, announce]);

  function run(id: number, servingsValue: string, then: After = "focus", nextDays = days) {
    const next = new URLSearchParams();
    next.set("food", String(id));
    if (servingsValue.trim()) next.set("servings", servingsValue.trim());
    next.set("days", String(nextDays));
    after.current = then;
    if (next.toString() === params.toString()) void check.refetch();
    else setParams(next);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    const text = servingsInput.trim();
    const n = parseNum(text);
    if (text && (n === null || n <= 0 || n > 100)) {
      setServingsError("Enter a number of servings above 0 (up to 100), or leave it blank.");
      focusElement(servingsRef.current);
      return;
    }
    setServingsError(null);
    run(selectedId, text);
  }

  function setDays(d: number) {
    const next = new URLSearchParams(params);
    next.set("days", String(d));
    if (foodId) after.current = "announce";
    setParams(next, { replace: true });
  }

  function choose(id: number, name: string) {
    setSelectedId(id);
    setSelectedName(name);
    focusSoon(() => selectedRef.current);
  }

  const shownName = selected.data?.name ?? selectedName ?? "this product";
  const result = check.data;
  const stale = check.isPlaceholderData && check.isFetching;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Supplement check</h1>
          <p className="muted">
            Does a supplement add anything your food and other supplements don't already provide? This compares amounts with reference intakes for
            healthy adults; it isn't medical advice.
          </p>
        </div>
        <div className="seg" role="group" aria-label="Compare with the last">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={days === p} className={days === p ? "active" : ""} onClick={() => setDays(p)}>
              {p} days
            </button>
          ))}
        </div>
      </div>

      <StackList
        days={days}
        onDetails={(it) => {
          setSelectedName(it.label);
          run(it.food_id!, "");
        }}
      />

      <section className="card stack" aria-labelledby="check-form-title">
        <h2 id="check-form-title">Check a product</h2>
        <form className="stack" onSubmit={submit} noValidate>
          {selectedId ? (
            <div className="selected" ref={selectedRef} tabIndex={-1} role="group" aria-label={`Chosen: ${shownName}`}>
              <div className="min-0">
                <strong>{shownName}</strong> {selected.data?.brand && <span className="muted">· {selected.data.brand}</span>}
                {selected.data && (
                  <div className="row wrap small">
                    <TrustBadge level={selected.data.trust_level} />
                    {selected.data.kind === "supplement" && <span className="chip">supplement</span>}
                    <span className="muted">{basisLabel(selected.data)}</span>
                  </div>
                )}
              </div>
              <button
                type="button"
                className="btn-link"
                onClick={() => {
                  setSelectedId(null);
                  setSelectedName(null);
                  focusSoon(() => document.querySelector<HTMLInputElement>(".picker input[type=search]"));
                }}
              >
                Change<VisuallyHidden> product</VisuallyHidden>
              </button>
            </div>
          ) : (
            <div className="stack-sm">
              <FoodPicker kind="supplement" placeholder="Search your supplements…" onPick={(f) => choose(f.id, f.name)} />
              <details className="online-search">
                <summary>Search online label databases (such as the NIH Dietary Supplement Label Database)</summary>
                <OnlineSearch onChoose={choose} />
              </details>
              <p className="muted small">
                Not listed anywhere? <Link to="/foods/new?kind=supplement">Enter a label by hand</Link>.
              </p>
            </div>
          )}
          <div className="servings-field">
            <Field
              label="Servings a day"
              hint={`Leave blank for the dose you usually log, or 1 serving${selected.data ? ` (${servingLabel(selected.data)})` : ""}.`}
              error={servingsError}
            >
              <input
                ref={servingsRef}
                inputMode="decimal"
                value={servingsInput}
                placeholder="Usual dose"
                onChange={(e) => setServingsInput(e.target.value)}
              />
            </Field>
          </div>
          <div>
            <Button type="submit" className="btn btn-primary" disabled={!selectedId || check.isFetching}>
              {check.isFetching && after.current === "focus" ? "Checking…" : "Check"}
            </Button>
          </div>
        </form>
      </section>

      {foodId && (
        <section className={`card stack check-result ${stale ? "is-stale" : ""}`} aria-labelledby="check-result-title" aria-busy={stale}>
          <h2 id="check-result-title" ref={resultHeading} tabIndex={-1}>
            Result for {result?.product.name ?? (selected.data?.id === foodId ? selected.data.name : "this product")}
          </h2>
          {check.isLoading && <Loading what="Checking" />}
          <ErrorBox error={check.error} />
          {result && <ResultView result={result} days={days} />}
        </section>
      )}
    </div>
  );
}
