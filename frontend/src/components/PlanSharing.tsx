import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import type { PlanPerson, PlanShares } from "../types";
import { ErrorBox, Field, Loading, ResultNote } from "./common";
import { Button, focusSoon, rescueFocus, useAnnounce, VisuallyHidden } from "./a11y";

/** Where a plan's sharing is read and changed: your own, or (for admins) any user's. */
export type ShareTarget =
  | { kind: "mine" }
  | { kind: "user"; id: number; name: string };

const sharesKey = (t: ShareTarget) => (t.kind === "mine" ? ["plan-shares"] : ["admin-plan-shares", t.id]);

function useShareApi(target: ShareTarget) {
  const qc = useQueryClient();
  const key = sharesKey(target);
  const shares = useQuery({
    queryKey: key,
    queryFn: () => (target.kind === "mine" ? api.planShares() : api.userPlanShares(target.id)),
  });
  // A change can show up on other lists too (an admin's own, another user's "can see" list).
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["plan-shares"] });
    qc.invalidateQueries({ queryKey: ["admin-plan-shares"] });
  };
  const store = (data: PlanShares) => {
    qc.setQueryData(key, data);
    refresh();
  };
  const grant = (email: string, canEdit: boolean) =>
    target.kind === "mine" ? api.sharePlan(email, canEdit) : api.shareUserPlan(target.id, email, canEdit);
  const revoke = (memberId: number) => (target.kind === "mine" ? api.unsharePlan(memberId) : api.unshareUserPlan(target.id, memberId));
  return { shares, grant, revoke, store, refresh };
}

const levelText = (canEdit: boolean) => (canEdit ? "can edit" : "view only");

function PersonName({ p }: { p: PlanPerson }) {
  return (
    <span className="min-0 break">
      <strong>{p.name}</strong>
      {p.display_name && <span className="muted small"> · {p.email}</span>}
    </span>
  );
}

function SharedWithRow({ p, target, headingId }: { p: PlanPerson; target: ShareTarget; headingId: string }) {
  const announce = useAnnounce();
  const { grant, revoke, store, refresh } = useShareApi(target);
  const whose = target.kind === "mine" ? "your plan" : `${target.name}'s plan`;
  const change = useMutation({
    mutationFn: () => grant(p.email, !p.can_edit),
    onSuccess: (data) => {
      store(data);
      announce(p.can_edit ? `${p.name} can now only view ${whose}.` : `${p.name} can now edit ${whose}.`);
    },
  });
  const remove = useMutation({
    mutationFn: () => revoke(p.user_id),
    onSuccess: () => {
      refresh();
      announce(`${p.name} can no longer see ${whose}.`);
      rescueFocus(() => document.getElementById(headingId));
    },
  });
  return (
    <li className="share-row">
      <div className="share-who">
        <PersonName p={p} />
        <span className={`chip ${p.can_edit ? "chip-ok" : ""}`}>{levelText(p.can_edit)}</span>
      </div>
      <div className="row wrap share-actions">
        <Button type="button" className="btn btn-sm" disabled={change.isPending || remove.isPending} onClick={() => change.mutate()}>
          {p.can_edit ? "Make view only" : "Allow editing"}
          <VisuallyHidden> for {p.name}</VisuallyHidden>
        </Button>
        <Button type="button" className="btn btn-sm danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          Remove<VisuallyHidden> {p.name}'s access</VisuallyHidden>
        </Button>
      </div>
      <ErrorBox error={change.error || remove.error} />
    </li>
  );
}

function ShareForm({ target }: { target: ShareTarget }) {
  const { grant, store } = useShareApi(target);
  const [email, setEmail] = useState("");
  const [canEdit, setCanEdit] = useState(true);
  const [done, setDone] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const radios = useId();
  const whose = target.kind === "mine" ? "your plan" : `${target.name}'s plan`;
  const share = useMutation({
    mutationFn: () => grant(email.trim(), canEdit),
    onMutate: () => setDone(null),
    onSuccess: (data) => {
      store(data);
      const p = data.shared_with.find((x) => x.email === email.trim().toLowerCase());
      setDone(`${p?.name ?? email.trim()} can now ${canEdit ? "see and edit" : "see"} ${whose}.`);
      setEmail("");
    },
    // Problems with the address (no such account, the plan's own) belong to the field.
    onError: (err) => {
      if (err instanceof ApiError && (err.status === 404 || err.status === 422)) focusSoon(() => emailRef.current);
    },
  });
  const fieldError = share.error instanceof ApiError && (share.error.status === 404 || share.error.status === 422) ? share.error.message : undefined;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (email.trim()) share.mutate();
  }
  return (
    <form className="stack-sm share-form" onSubmit={submit} aria-label={`Share ${whose}`}>
      <Field label="Share with (email)" hint="They need an account on this server." error={fieldError}>
        <input
          ref={emailRef}
          type="email"
          required
          value={email}
          autoComplete="off"
          onChange={(e) => {
            setEmail(e.target.value);
            if (share.error) share.reset();
          }}
        />
      </Field>
      <fieldset className="fieldset">
        <legend>What they can do</legend>
        <label className="radio">
          <input type="radio" name={radios} checked={canEdit} onChange={() => setCanEdit(true)} />
          Can edit (plan meals, tick off shopping)
        </label>
        <label className="radio">
          <input type="radio" name={radios} checked={!canEdit} onChange={() => setCanEdit(false)} />
          View only
        </label>
      </fieldset>
      <div>
        <Button type="submit" className="btn btn-primary btn-sm" disabled={share.isPending || !email.trim()}>
          {share.isPending ? "Sharing…" : "Share"}
        </Button>
      </div>
      {!fieldError && <ErrorBox error={share.error} />}
      {done && <ResultNote ok>{done}</ResultNote>}
    </form>
  );
}

function SharedWithMeRow({ p, headingId }: { p: PlanPerson; headingId: string }) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const leave = useMutation({
    mutationFn: () => api.leaveSharedPlan(p.user_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan-shares"] });
      announce(`You no longer see ${p.name}'s plan.`);
      rescueFocus(() => document.getElementById(headingId));
    },
  });
  return (
    <li className="share-row">
      <div className="share-who">
        <PersonName p={p} />
        <span className={`chip ${p.can_edit ? "chip-ok" : ""}`}>{p.can_edit ? "you can edit" : "view only"}</span>
      </div>
      <div className="row wrap share-actions">
        <Link className="btn btn-sm" to={`/plan?of=${p.user_id}`}>
          Open<VisuallyHidden> {p.name}'s plan</VisuallyHidden>
        </Link>
        <Button
          type="button"
          className="btn btn-sm danger"
          disabled={leave.isPending}
          onClick={() => {
            if (confirm(`Stop seeing ${p.name}'s plan? They can share it with you again.`)) leave.mutate();
          }}
        >
          Stop seeing<VisuallyHidden> {p.name}'s plan</VisuallyHidden>
        </Button>
      </div>
      <ErrorBox error={leave.error} />
    </li>
  );
}

/**
 * Who can see (or edit) a plan, with change/remove actions and an add form; for your own plan also the
 * plans shared with you. `level` is the heading level of the sub-sections.
 */
export function PlanSharing({ target, level = 3 }: { target: ShareTarget; level?: 2 | 3 | 4 }) {
  const { shares } = useShareApi(target);
  const base = useId();
  const withId = `${base}-with`;
  const meId = `${base}-me`;
  const H = `h${level}` as "h2" | "h3" | "h4";
  const mine = target.kind === "mine";
  const whose = mine ? "your plan" : `${target.name}'s plan`;
  if (shares.isLoading) return <Loading />;
  const data = shares.data;
  return (
    <div className="stack plan-sharing">
      <ErrorBox error={shares.error} />
      {data && (
        <section className="stack-sm" aria-labelledby={withId}>
          <H id={withId} className="h-card" tabIndex={-1}>
            Who can see {whose}
          </H>
          {data.shared_with.length === 0 ? (
            <p className="muted small">{mine ? "You haven't shared your plan with anyone." : `Nobody else can see ${target.name}'s plan.`}</p>
          ) : (
            <ul className="plain-list share-list">
              {data.shared_with.map((p) => (
                <SharedWithRow key={p.user_id} p={p} target={target} headingId={withId} />
              ))}
            </ul>
          )}
          <p className="muted small">
            {mine ? "People you share with" : "People with access"} see the plan and shopping list, with {mine ? "your" : `${target.name}'s`} targets. Only{" "}
            {mine ? "you" : target.name} can log from it.
          </p>
          <ShareForm target={target} />
        </section>
      )}
      {data && mine && (
        <section className="stack-sm" aria-labelledby={meId}>
          <H id={meId} className="h-card" tabIndex={-1}>
            Plans shared with you
          </H>
          {data.shared_with_me.length === 0 ? (
            <p className="muted small">Nobody has shared their plan with you.</p>
          ) : (
            <ul className="plain-list share-list">
              {data.shared_with_me.map((p) => (
                <SharedWithMeRow key={p.user_id} p={p} headingId={meId} />
              ))}
            </ul>
          )}
        </section>
      )}
      {data && !mine && data.shared_with_me.length > 0 && (
        <p className="muted small">
          {target.name} can see: {data.shared_with_me.map((p) => `${p.name}'s plan (${levelText(p.can_edit)})`).join(", ")}.
        </p>
      )}
    </div>
  );
}
