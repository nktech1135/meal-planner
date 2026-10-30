import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components/common";
import { addDays, fmt1, fmtGrams, fmtShortDate, mondayOf, todayISO, useUnitSystem } from "../lib";
import type { ShoppingItem, ShoppingList, UnitSystem } from "../types";
import { Button, titleText } from "../components/a11y";
import { useAuth } from "../auth";

const ISO = /^\d{4}-\d{2}-\d{2}$/;

function amountText(it: ShoppingItem, u: UnitSystem): string {
  if (it.unit === "g") return fmtGrams(it.amount, u);
  return `${fmt1(it.amount)} ${it.unit}`;
}

export default function ShoppingPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const units = useUnitSystem();
  const today = todayISO();
  const start = ISO.test(params.get("start") ?? "") ? params.get("start")! : today;
  const endParam = ISO.test(params.get("end") ?? "") ? params.get("end")! : addDays(mondayOf(today), 6);
  const end = endParam < start ? start : endParam;
  // ?of=<owner id>: the list for a plan someone shared with you. Ticks are shared; they need edit rights.
  const { user } = useAuth();
  const ofParam = Number(params.get("of"));
  const of = Number.isInteger(ofParam) && ofParam > 0 && ofParam !== user?.id ? ofParam : null;
  const shares = useQuery({ queryKey: ["plan-shares"], queryFn: api.planShares, enabled: of !== null });
  const owner = of ? (shares.data?.shared_with_me.find((p) => p.user_id === of) ?? null) : null;
  const canTick = of === null || !!owner?.can_edit;
  useEffect(() => {
    document.title = titleText(owner ? `${owner.name}'s shopping list` : "Shopping list");
  }, [owner]);
  const key = ["shopping", start, end, of];
  // Ticks show immediately; the server copy catches up.
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const list = useQuery({ queryKey: key, queryFn: () => api.shopping(start, end, of), placeholderData: (prev) => prev });
  const check = useMutation({
    mutationFn: (v: { key: string; checked: boolean }) => api.checkShopping(start, end, v.key, v.checked, of),
    onMutate: (v) => {
      qc.setQueryData<ShoppingList>(key, (old) => (old ? { ...old, items: old.items.map((i) => (i.key === v.key ? { ...i, checked: v.checked } : i)) } : old));
    },
    onError: (_e, v) => {
      setTicked((t) => ({ ...t, [v.key]: !v.checked }));
      qc.invalidateQueries({ queryKey: key });
    },
  });

  const set = (k: "start" | "end", v: string) => {
    if (!ISO.test(v)) return;
    const next = new URLSearchParams(params);
    next.set(k, v);
    if (k === "start" && v > end) next.set("end", v);
    setParams(next, { replace: true });
  };

  const items = (list.data?.items ?? []).map((i) => (i.key in ticked ? { ...i, checked: ticked[i.key] } : i));
  const groups: string[] = [];
  for (const i of items) if (!groups.includes(i.category)) groups.push(i.category);
  const done = items.filter((i) => i.checked).length;
  const planLink = `/plan?date=${start}${of ? `&of=${of}` : ""}`;
  const tooLong = (new Date(`${end}T12:00:00`).getTime() - new Date(`${start}T12:00:00`).getTime()) / 86_400_000 >= 62;

  return (
    <div className="stack shopping">
      <div className="page-head">
        <div>
          <p className="no-print small">
            <Link to={planLink}>
              <span aria-hidden="true">← </span>
              <span className="sr-only">Back to </span>Plan
            </Link>
          </p>
          <h1>{owner ? `${owner.name}'s shopping list` : "Shopping list"}</h1>
          <p className="muted small print-only">
            {fmtShortDate(start)} – {fmtShortDate(end)}
          </p>
        </div>
        <Button type="button" className="btn no-print" onClick={() => window.print()} disabled={!items.length}>
          Print
        </Button>
      </div>
      {owner && (
        <div className="alert alert-info owner-banner no-print" role="note" aria-label="Whose list">
          <p>
            <strong>You're viewing {owner.name}'s shopping list</strong> · {owner.can_edit ? "you can tick items off" : "view only"}.
          </p>
          <p className="small">
            {owner.can_edit
              ? `Ticks are shared: ${owner.name} and everyone who can edit their plan see them.`
              : `Only people who can edit ${owner.name}'s plan can tick items off.`}
          </p>
        </div>
      )}
      <form className="card row wrap align-end no-print" onSubmit={(e) => e.preventDefault()} aria-label="Dates to shop for">
        <Field label="From">
          <input type="date" value={start} onChange={(e) => set("start", e.target.value)} required />
        </Field>
        <Field label="To">
          <input type="date" value={end} min={start} onChange={(e) => set("end", e.target.value)} required />
        </Field>
        <p className="muted small grow">
          Everything planned and not yet logged in these days. Recipes are broken down into ingredients; foods weighed cooked are converted back to
          raw weight.
        </p>
      </form>
      {tooLong && <div className="alert alert-warn no-print">Choose a range of up to 62 days.</div>}
      <ErrorBox error={!tooLong && list.error} />
      {list.isLoading && <Loading />}
      {list.data && items.length === 0 && (
        <p className="muted">
          Nothing to buy for these days. <Link to={planLink}>Plan some meals</Link> first.
        </p>
      )}
      {items.length > 0 && (
        <p className="muted small no-print" role="status">
          {done} of {items.length} ticked off.
        </p>
      )}
      {groups.map((g, gi) => (
        <section key={g} className="card shop-group" aria-labelledby={`shop-cat-${gi}`}>
          <h2 id={`shop-cat-${gi}`} className="h-card">
            {g}
          </h2>
          <ul className="plain-list">
            {items
              .filter((i) => i.category === g)
              .map((i) => (
                <li key={i.key} className={`shop-item ${i.checked ? "is-checked" : ""}`}>
                  <label className="shop-label">
                    <input type="checkbox" checked={i.checked} disabled={!canTick} onChange={(e) => {
                        const checked = e.target.checked;
                        setTicked((t) => ({ ...t, [i.key]: checked }));
                        check.mutate({ key: i.key, checked });
                      }} />
                    <span className="shop-text">
                      <span className="shop-name">
                        {i.name}
                        {i.brand && <span className="muted"> · {i.brand}</span>}
                      </span>
                      {i.used_for.some((u) => !u.startsWith(i.name)) && <span className="shop-for muted small">for {i.used_for.join(", ")}</span>}
                    </span>
                    <strong className="shop-amount">{amountText(i, units)}</strong>
                  </label>
                </li>
              ))}
          </ul>
        </section>
      ))}
      <ErrorBox error={check.error} />
    </div>
  );
}
