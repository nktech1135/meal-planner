import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { activeProfile, switchProfile } from "../profile";
import type { PlanPerson, PlanShares } from "../types";
import { ErrorBox, Field, Loading, ResultNote } from "./common";
import { Button, focusSoon, rescueFocus, useAnnounce, VisuallyHidden } from "./a11y";

/**
 * What is shared: a meal plan (and its shopping list), or a whole profile, which the people it's
 * shared with can switch to and use as if they were its owner.
 */
export type ShareScope = "plan" | "profile";

/** Whose sharing is read and changed: your own, or (for admins) any user's. */
export type ShareTarget =
  | { kind: "mine" }
  | { kind: "user"; id: number; name: string };

const SCOPES = {
  plan: {
    thing: "plan",
    things: "Plans",
    key: "plan-shares",
    adminKey: "admin-plan-shares",
    see: "see",
    editHint: "plan meals, tick off shopping",
    mine: () => api.planShares(),
    user: (id: number) => api.userPlanShares(id),
    grantMine: (email: string, canEdit: boolean) => api.sharePlan(email, canEdit),
    grantUser: (id: number, email: string, canEdit: boolean) => api.shareUserPlan(id, email, canEdit),
    revokeMine: (memberId: number) => api.unsharePlan(memberId),
    revokeUser: (id: number, memberId: number) => api.unshareUserPlan(id, memberId),
    leave: (ownerId: number) => api.leaveSharedPlan(ownerId),
  },
  profile: {
    thing: "profile",
    things: "Profiles",
    key: "profile-access",
    adminKey: "admin-profile-access",
    see: "use",
    editHint: "log food and change anything in the profile",
    mine: () => api.profileAccess(),
    user: (id: number) => api.userProfileAccess(id),
    grantMine: (email: string, canEdit: boolean) => api.shareProfile(email, canEdit),
    grantUser: (id: number, email: string, canEdit: boolean) => api.shareUserProfile(id, email, canEdit),
    revokeMine: (memberId: number) => api.unshareProfile(memberId),
    revokeUser: (id: number, memberId: number) => api.unshareUserProfile(id, memberId),
    leave: (ownerId: number) => api.leaveSharedProfile(ownerId),
  },
};

const sharesKey = (scope: ShareScope, t: ShareTarget) =>
  t.kind === "mine" ? [SCOPES[scope].key] : [SCOPES[scope].adminKey, t.id];

function useShareApi(scope: ShareScope, target: ShareTarget) {
  const qc = useQueryClient();
  const s = SCOPES[scope];
  const key = sharesKey(scope, target);
  const shares = useQuery({
    queryKey: key,
    queryFn: () => (target.kind === "mine" ? s.mine() : s.user(target.id)),
  });
  // A change can show up on other lists too (an admin's own, another user's "can see" list).
  const refresh = () => {
    qc.invalidateQueries({ queryKey: [s.key] });
    qc.invalidateQueries({ queryKey: [s.adminKey] });
  };
  const store = (data: PlanShares) => {
    qc.setQueryData(key, data);
    refresh();
  };
  const grant = (email: string, canEdit: boolean) =>
    target.kind === "mine" ? s.grantMine(email, canEdit) : s.grantUser(target.id, email, canEdit);
  const revoke = (memberId: number) => (target.kind === "mine" ? s.revokeMine(memberId) : s.revokeUser(target.id, memberId));
  return { shares, grant, revoke, store, refresh };
}

/** The profiles shared with you, to switch to. */
export function useSharedProfiles() {
  return useQuery({ queryKey: [SCOPES.profile.key], queryFn: () => api.profileAccess(), staleTime: 60_000 });
}

const levelText = (canEdit: boolean) => (canEdit ? "can edit" : "view only");
const whoseText = (scope: ShareScope, target: ShareTarget) =>
  target.kind === "mine" ? `your ${SCOPES[scope].thing}` : `${target.name}'s ${SCOPES[scope].thing}`;

function PersonName({ p }: { p: PlanPerson }) {
  return (
    <span className="min-0 break">
      <strong>{p.name}</strong>
      {p.display_name && <span className="muted small"> · {p.email}</span>}
    </span>
  );
}

type RowProps = { p: PlanPerson; scope: ShareScope; target: ShareTarget; headingId: string };

function SharedWithRow({ p, scope, target, headingId }: RowProps) {
  const announce = useAnnounce();
  const { grant, revoke, store, refresh } = useShareApi(scope, target);
  const whose = whoseText(scope, target);
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
      announce(`${p.name} can no longer ${SCOPES[scope].see} ${whose}.`);
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

function ShareForm({ scope, target }: { scope: ShareScope; target: ShareTarget }) {
  const { grant, store } = useShareApi(scope, target);
  const [email, setEmail] = useState("");
  const [canEdit, setCanEdit] = useState(true);
  const [done, setDone] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const radios = useId();
  const whose = whoseText(scope, target);
  const see = SCOPES[scope].see;
  const share = useMutation({
    mutationFn: () => grant(email.trim(), canEdit),
    onMutate: () => setDone(null),
    onSuccess: (data) => {
      store(data);
      const p = data.shared_with.find((x) => x.email === email.trim().toLowerCase());
      setDone(`${p?.name ?? email.trim()} can now ${see}${canEdit ? " and edit" : ""} ${whose}.`);
      setEmail("");
    },
    // Problems with the address (no such account, the owner's own) belong to the field.
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
          Can edit ({SCOPES[scope].editHint})
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

function SharedWithMeRow({ p, scope, headingId }: { p: PlanPerson; scope: ShareScope; headingId: string }) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const s = SCOPES[scope];
  const using = scope === "profile" && activeProfile()?.id === p.user_id;
  const leave = useMutation({
    mutationFn: () => s.leave(p.user_id),
    onSuccess: () => {
      if (using) {
        switchProfile(null, `You gave up access to ${p.name}'s profile.`);
        return;
      }
      qc.invalidateQueries({ queryKey: [s.key] });
      announce(`You no longer ${s.see} ${p.name}'s ${s.thing}.`);
      rescueFocus(() => document.getElementById(headingId));
    },
  });
  const stop = scope === "plan" ? "Stop seeing" : "Give up access";
  return (
    <li className="share-row">
      <div className="share-who">
        <PersonName p={p} />
        <span className={`chip ${p.can_edit ? "chip-ok" : ""}`}>{p.can_edit ? "you can edit" : "view only"}</span>
        {using && <span className="chip">in use</span>}
      </div>
      <div className="row wrap share-actions">
        {scope === "plan" ? (
          <Link className="btn btn-sm" to={`/plan?of=${p.user_id}`}>
            Open<VisuallyHidden> {p.name}'s plan</VisuallyHidden>
          </Link>
        ) : (
          !using && (
            <Button type="button" className="btn btn-sm" onClick={() => switchProfile({ id: p.user_id, name: p.name })}>
              Switch to<VisuallyHidden> {p.name}'s profile</VisuallyHidden>
            </Button>
          )
        )}
        <Button
          type="button"
          className="btn btn-sm danger"
          disabled={leave.isPending}
          onClick={() => {
            if (confirm(`${stop} ${p.name}'s ${s.thing}? They can share it with you again.`)) leave.mutate();
          }}
        >
          {stop}
          <VisuallyHidden> {p.name}'s {s.thing}</VisuallyHidden>
        </Button>
      </div>
      <ErrorBox error={leave.error} />
    </li>
  );
}

function Explainer({ scope, target }: { scope: ShareScope; target: ShareTarget }) {
  const mine = target.kind === "mine";
  const owner = mine ? "you" : target.name;
  const ownerPossessive = mine ? "your" : `${target.name}'s`;
  if (scope === "plan") {
    return (
      <p className="muted small">
        {mine ? "People you share with" : "People with access"} see the plan and shopping list, with {ownerPossessive} targets. Only{" "}
        {owner} can log from it.
      </p>
    );
  }
  return (
    <p className="muted small">
      People with access can switch to {ownerPossessive} profile and see everything in it: food log, foods, recipes, plan,
      body measurements, targets and advisor chats. With editing allowed, they can change all of it as if they were {owner};
      anything they log or plan shows who added it. They never see {ownerPossessive} email or password, and can't change who has
      access.
    </p>
  );
}

/**
 * Who can see (or edit) a plan or profile, with change/remove actions and an add form; for your own also
 * those shared with you. `level` is the heading level of the sub-sections.
 */
export function Sharing({ scope, target, level = 3 }: { scope: ShareScope; target: ShareTarget; level?: 2 | 3 | 4 }) {
  const { shares } = useShareApi(scope, target);
  const s = SCOPES[scope];
  const base = useId();
  const withId = `${base}-with`;
  const meId = `${base}-me`;
  const H = `h${level}` as "h2" | "h3" | "h4";
  const mine = target.kind === "mine";
  const whose = whoseText(scope, target);
  if (shares.isLoading) return <Loading />;
  const data = shares.data;
  return (
    <div className="stack plan-sharing">
      <ErrorBox error={shares.error} />
      {data && (
        <section className="stack-sm" aria-labelledby={withId}>
          <H id={withId} className="h-card" tabIndex={-1}>
            Who can {s.see} {whose}
          </H>
          {data.shared_with.length === 0 ? (
            <p className="muted small">{mine ? `You haven't shared your ${s.thing} with anyone.` : `Nobody else can ${s.see} ${whose}.`}</p>
          ) : (
            <ul className="plain-list share-list">
              {data.shared_with.map((p) => (
                <SharedWithRow key={p.user_id} p={p} scope={scope} target={target} headingId={withId} />
              ))}
            </ul>
          )}
          <Explainer scope={scope} target={target} />
          <ShareForm scope={scope} target={target} />
        </section>
      )}
      {data && mine && (
        <section className="stack-sm" aria-labelledby={meId}>
          <H id={meId} className="h-card" tabIndex={-1}>
            {s.things} shared with you
          </H>
          {data.shared_with_me.length === 0 ? (
            <p className="muted small">Nobody has shared their {s.thing} with you.</p>
          ) : (
            <ul className="plain-list share-list">
              {data.shared_with_me.map((p) => (
                <SharedWithMeRow key={p.user_id} p={p} scope={scope} headingId={meId} />
              ))}
            </ul>
          )}
        </section>
      )}
      {data && !mine && data.shared_with_me.length > 0 && (
        <p className="muted small">
          {target.name} can {s.see}: {data.shared_with_me.map((p) => `${p.name}'s ${s.thing} (${levelText(p.can_edit)})`).join(", ")}.
        </p>
      )}
    </div>
  );
}
