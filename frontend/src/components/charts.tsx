import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { fmtShortDate, weekdayShort } from "../lib";

/*
 * Small hand-written SVG charts (no chart library). Conventions (see the dataviz method):
 * thin bars (<= 24 px) with a 4 px rounded data end, 2 px lines, >= 8 px dots with a 2 px surface ring,
 * hairline solid grid, one y-axis, text in text colours (never the series colour), a hover/focus
 * tooltip that never gates a value (every chart has a table view).
 */

const H = 200; // plot + axis band; the container is sized to include the x-axis labels
const M = { top: 14, right: 10, bottom: 24, left: 42 };

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** 3–5 round tick values covering [lo, hi]. */
function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 10_000) return `${Math.round(v / 1000)}K`;
  if (a >= 1000) return `${(v / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  if (a >= 100) return String(Math.round(v));
  return String(Number(v.toPrecision(3)));
}

/** Which day indexes get an x-axis label: all for a week, otherwise a few evenly spaced incl. first and last. */
function labelIndexes(n: number, width: number): Set<number> {
  if (n <= 7 && width >= 300) return new Set(Array.from({ length: n }, (_, i) => i));
  const slots = Math.max(2, Math.min(6, Math.floor(width / 64)));
  const out = new Set<number>();
  for (let k = 0; k < slots; k++) out.add(Math.round((k * (n - 1)) / (slots - 1)));
  return out;
}

/** Edge labels hug the plot edges so they never spill past it. */
const anchorFor = (i: number, n: number) => (n <= 7 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle");

const dayLabel = (d: string, n: number) => (n <= 7 ? weekdayShort(d) : fmtShortDate(d));

/** Rounded top (data end) and square bottom (baseline). */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function Tooltip({ x, width, children }: { x: number; width: number; children: ReactNode }) {
  // Keep the box inside the chart: anchor left/right depending on the side.
  const right = x > width / 2;
  return (
    <div className="viz-tip" style={right ? { right: width - x + 8 } : { left: x + 8 }} role="presentation">
      {children}
    </div>
  );
}

/**
 * Reference-line labels sit just above their line, in the right-most stretch of days whose bars don't reach
 * it (right end when nothing is in the way). With no clear stretch, or when two labels would collide, the label
 * is left out; the legend always names every line with its value.
 */
function placeRefLabels(
  refs: RefLine[],
  days: DayValue[],
  y: (v: number) => number,
  colX: (i: number) => number,
  band: number,
  rightEdge: number,
): { r: RefLine; x: number | null }[] {
  const n = days.length;
  const placed: { y: number; x0: number; x1: number }[] = [];
  return refs.map((r) => {
    const w = r.label.length * 6.2 + 6;
    const cols = Math.max(1, Math.ceil(w / Math.max(band, 1)));
    const ry = y(r.value);
    const clear = (end: number) => {
      for (let i = Math.max(0, end - cols + 1); i <= end; i++) if ((days[i]?.value ?? 0) >= r.value * 0.97) return false;
      return true;
    };
    let x: number | null = null; // no clear stretch: leave it to the legend
    for (let end = n - 1; end >= cols - 1; end--) {
      if (clear(end)) {
        x = end === n - 1 ? rightEdge : colX(end) + band / 2;
        break;
      }
    }
    if (x === null || placed.some((p) => Math.abs(p.y - ry) < 14 && x! - w < p.x1 && x! > p.x0)) return { r, x: null };
    placed.push({ y: ry, x0: x - w, x1: x });
    return { r, x };
  });
}

export type RefLine = { value: number; label: string; kind: "target" | "min" | "max" | "range" };

export type DayValue = { date: string; value: number | null }; // null: nothing logged that day

/** Daily bars against reference lines (target/min/limit). Unlogged days get a hollow baseline marker. */
export function DailyBars({
  days,
  refs,
  unit,
  label,
  format,
}: {
  days: DayValue[];
  refs: RefLine[];
  unit: string;
  label: string;
  format: (v: number) => string;
}) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const tableId = useId();
  const n = days.length;
  const values = days.map((d) => d.value ?? 0);
  const top = Math.max(...values, ...refs.map((r) => r.value), 1) * 1.12;
  const ticks = niceTicks(0, top);
  const yMax = Math.max(top, ticks[ticks.length - 1]);
  const pw = Math.max(0, width - M.left - M.right);
  const ph = H - M.top - M.bottom;
  const band = n ? pw / n : 0;
  const barW = Math.max(1, Math.min(24, band - 2, band * 0.72));
  const x = (i: number) => M.left + i * band + band / 2;
  const y = (v: number) => M.top + ph - (v / yMax) * ph;
  const labels = labelIndexes(n, pw);

  function onKey(e: KeyboardEvent) {
    if (!n) return;
    const cur = active ?? n - 1;
    const next = e.key === "ArrowLeft" ? cur - 1 : e.key === "ArrowRight" ? cur + 1 : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (next === null) return;
    e.preventDefault();
    setActive(Math.max(0, Math.min(n - 1, next)));
  }

  const a = active !== null ? days[active] : null;
  return (
    <div className="viz">
      <div
        ref={wrap}
        className="viz-plot"
        style={{ height: H }}
        tabIndex={0}
        role="group"
        aria-label={`${label}. Use the left and right arrow keys to read each day; the table below lists every value.`}
        onKeyDown={onKey}
        onFocus={() => setActive((v) => v ?? n - 1)}
        onBlur={() => setActive(null)}
        onPointerLeave={() => setActive(null)}
      >
        {width > 0 && (
          <svg width={width} height={H} aria-hidden="true" className="viz-svg">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} className={t === 0 ? "viz-axis" : "viz-grid"} />
                <text x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">
                  {compact(t)}
                </text>
              </g>
            ))}
            {days.map((d, i) => {
              const cx = x(i);
              if (d.value === null) {
                return band >= 7 ? (
                  <circle key={d.date} cx={cx} cy={M.top + ph - 4} r={3} className="viz-unlogged" />
                ) : (
                  <rect key={d.date} x={cx - barW / 2} y={M.top + ph - 3} width={barW} height={3} className="viz-unlogged-tick" />
                );
              }
              const h = Math.max(0, M.top + ph - y(d.value));
              return (
                <path
                  key={d.date}
                  d={barPath(cx - barW / 2, y(d.value), barW, h)}
                  className={`viz-bar ${active === i ? "is-active" : ""}`}
                />
              );
            })}
            {placeRefLabels(refs, days, y, (i) => x(i), band, width - M.right).map(({ r, x: lx }) => (
              <g key={r.kind}>
                <line x1={M.left} x2={width - M.right} y1={y(r.value)} y2={y(r.value)} className={`viz-ref viz-ref-${r.kind}`} />
                {lx !== null && (
                  <text x={lx} y={y(r.value) - 4} textAnchor="end" className="viz-ref-label">
                    {r.label}
                  </text>
                )}
              </g>
            ))}
            {[...labels].map((i) => (
              <text key={i} x={x(i)} y={H - 6} textAnchor={anchorFor(i, n)} className="viz-tick">
                {dayLabel(days[i].date, n)}
              </text>
            ))}
            {active !== null && <line x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + ph} className="viz-cross" />}
            {/* hit areas: the whole day column, wider than the bar */}
            {days.map((d, i) => (
              <rect
                key={`hit-${d.date}`}
                x={M.left + i * band}
                y={M.top}
                width={band}
                height={ph}
                fill="transparent"
                onPointerMove={() => setActive(i)}
                onPointerDown={() => setActive(i)}
              />
            ))}
          </svg>
        )}
        {a && active !== null && (
          <Tooltip x={x(active)} width={width}>
            <strong>{a.value === null ? "Not logged" : `${format(a.value)} ${unit}`}</strong>
            <span>{new Date(`${a.date}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}</span>
          </Tooltip>
        )}
      </div>
      <div className="viz-legend small">
        <span>
          <span className="key-swatch key-bar" aria-hidden="true" /> logged day
        </span>
        <span>
          <span className="key-swatch key-unlogged" aria-hidden="true" /> not logged
        </span>
        {refs.map((r) => (
          <span key={r.kind}>
            <span className={`key-line key-ref-${r.kind}`} aria-hidden="true" /> {r.label}
          </span>
        ))}
      </div>
      <details className="viz-table">
        <summary aria-controls={tableId}>Show as table</summary>
        <div className="table-wrap" id={tableId}>
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">
                  {label} ({unit})
                </th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date}>
                  <td>{fmtShortDate(d.date)}</td>
                  <td className="num">{d.value === null ? <span className="muted">not logged</span> : format(d.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export type WeightDatum = { date: string; reading: number; trend: number };

/** Scale readings (grey dots, context) and the smoothed trend (the accent line, the point). */
export function WeightChart({ dates, points, unit, format }: { dates: string[]; points: WeightDatum[]; unit: string; format: (v: number) => string }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null); // index into points
  const tableId = useId();
  const n = dates.length;
  const idx = new Map(dates.map((d, i) => [d, i]));
  const all = points.flatMap((p) => [p.reading, p.trend]);
  const lo0 = Math.min(...all);
  const hi0 = Math.max(...all);
  const pad = Math.max((hi0 - lo0) * 0.15, 0.5);
  const ticks = niceTicks(lo0 - pad, hi0 + pad);
  const lo = Math.min(lo0 - pad, ticks[0]);
  const hi = Math.max(hi0 + pad, ticks[ticks.length - 1]);
  const pw = Math.max(0, width - M.left - M.right - 46); // room for the end label
  const ph = H - M.top - M.bottom;
  const x = (d: string) => M.left + (n > 1 ? ((idx.get(d) ?? 0) / (n - 1)) * pw : pw / 2);
  const y = (v: number) => M.top + ph - ((v - lo) / (hi - lo)) * ph;
  const labels = labelIndexes(n, pw);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.trend).toFixed(1)}`).join("");
  const last = points[points.length - 1];

  function nearest(px: number) {
    let best = 0;
    let dist = Infinity;
    points.forEach((p, i) => {
      const dd = Math.abs(x(p.date) - px);
      if (dd < dist) {
        dist = dd;
        best = i;
      }
    });
    setActive(best);
  }
  function onKey(e: KeyboardEvent) {
    const cur = active ?? points.length - 1;
    const next = e.key === "ArrowLeft" ? cur - 1 : e.key === "ArrowRight" ? cur + 1 : e.key === "Home" ? 0 : e.key === "End" ? points.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    setActive(Math.max(0, Math.min(points.length - 1, next)));
  }
  const a = active !== null ? points[active] : null;

  return (
    <div className="viz">
      <div
        ref={wrap}
        className="viz-plot"
        style={{ height: H }}
        tabIndex={0}
        role="group"
        aria-label="Weight: scale readings and trend. Use the left and right arrow keys to read each weigh-in; the table below lists every value."
        onKeyDown={onKey}
        onFocus={() => setActive((v) => v ?? points.length - 1)}
        onBlur={() => setActive(null)}
        onPointerLeave={() => setActive(null)}
        onPointerMove={(e) => nearest(e.clientX - e.currentTarget.getBoundingClientRect().left)}
        onPointerDown={(e) => nearest(e.clientX - e.currentTarget.getBoundingClientRect().left)}
      >
        {width > 0 && (
          <svg width={width} height={H} aria-hidden="true" className="viz-svg">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={M.left + pw} y1={y(t)} y2={y(t)} className="viz-grid" />
                <text x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">
                  {compact(t)}
                </text>
              </g>
            ))}
            <line x1={M.left} x2={M.left + pw} y1={M.top + ph} y2={M.top + ph} className="viz-axis" />
            {[...labels].map((i) => (
              <text key={i} x={x(dates[i])} y={H - 6} textAnchor={anchorFor(i, n)} className="viz-tick">
                {dayLabel(dates[i], n)}
              </text>
            ))}
            {a && <line x1={x(a.date)} x2={x(a.date)} y1={M.top} y2={M.top + ph} className="viz-cross" />}
            {points.map((p) => (
              <circle key={p.date} cx={x(p.date)} cy={y(p.reading)} r={4} className="viz-dot" />
            ))}
            {points.length > 1 && <path d={line} className="viz-line" />}
            {last && (
              <>
                <circle cx={x(last.date)} cy={y(last.trend)} r={4} className="viz-line-end" />
                <text x={x(last.date) + 8} y={y(last.trend)} dy="0.32em" className="viz-end-label">
                  {format(last.trend)} {unit}
                </text>
              </>
            )}
            {a && <circle cx={x(a.date)} cy={y(a.trend)} r={5} className="viz-line-end" />}
          </svg>
        )}
        {a && (
          <Tooltip x={x(a.date)} width={width}>
            <span className="tip-row">
              <span className="key-line key-trend" aria-hidden="true" /> <strong>{format(a.trend)} {unit}</strong> trend
            </span>
            <span className="tip-row">
              <span className="key-dot" aria-hidden="true" /> <strong>{format(a.reading)} {unit}</strong> scale
            </span>
            <span>{new Date(`${a.date}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}</span>
          </Tooltip>
        )}
      </div>
      <div className="viz-legend small">
        <span>
          <span className="key-line key-trend" aria-hidden="true" /> trend (smoothed)
        </span>
        <span>
          <span className="key-dot" aria-hidden="true" /> scale reading
        </span>
      </div>
      <details className="viz-table">
        <summary aria-controls={tableId}>Show as table</summary>
        <div className="table-wrap" id={tableId}>
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">Scale ({unit})</th>
                <th className="num">Trend ({unit})</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.date}>
                  <td>{fmtShortDate(p.date)}</td>
                  <td className="num">{format(p.reading)}</td>
                  <td className="num">{format(p.trend)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
