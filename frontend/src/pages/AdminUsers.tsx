import { useId, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { AdminFrame } from "../components/AdminTabs";
import { CopyField, ErrorBox, Field, Loading, ResultNote } from "../components/common";
import type { AdminUser, InviteResult } from "../types";
import { Button, focusSoon, rescueFocus, useAnnounce, VisuallyHidden } from "../components/a11y";
import { PlanSharing } from "../components/PlanSharing";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }) : "never");

type SignIn = "invite" | "password";

/** Create an account: with a password the admin sets and passes on, or with an invite link. */
function AddUserForm() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [how, setHow] = useState<SignIn>("invite");
  const [password, setPassword] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [result, setResult] = useState<InviteResult | null>(null);
  const radios = useId();
  const withPassword = how === "password";
  const mismatch = withPassword && (confirmPw !== "" || submitted) && password !== confirmPw;
  const add = useMutation({
    mutationFn: () =>
      api.addUser({ email: email.trim(), display_name: name.trim(), is_admin: admin, ...(withPassword ? { password } : {}) }),
    onMutate: () => setResult(null),
    onSuccess: (r) => {
      setResult(r);
      // The password is never shown again; the admin already knows it.
      setEmail("");
      setName("");
      setPassword("");
      setConfirmPw("");
      setShowPw(false);
      setAdmin(false);
      setSubmitted(false);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitted(true);
    // Required/length checks are the browser's; the match check is ours: say so and go to the field.
    if (withPassword && password !== confirmPw) focusSoon(() => document.getElementById("new-user-confirm-password"));
    else if (!withPassword || password.length >= 10) add.mutate();
  }
  const pwType = showPw ? "text" : "password";
  return (
    <section className="card stack" aria-labelledby="add-user-title">
      <h2 id="add-user-title">Add a user</h2>
      <p className="muted small">Creates the account, even with sign-ups closed.</p>
      <form className="stack-sm" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Email">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Name (optional)">
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoComplete="off" />
          </Field>
        </div>
        <fieldset className="fieldset stack-sm">
          <legend>How they get in</legend>
          <div className="stack-xs">
            <label className="radio">
              <input type="radio" name={radios} checked={how === "invite"} onChange={() => setHow("invite")} aria-describedby={`${radios}-invite`} />
              Send an invite link
            </label>
            <span id={`${radios}-invite`} className="field-hint radio-hint">They choose their own password from a link (emailed to them if email is set up).</span>
          </div>
          <div className="stack-xs">
            <label className="radio">
              <input type="radio" name={radios} checked={withPassword} onChange={() => setHow("password")} aria-describedby={`${radios}-password`} />
              Set a password now
            </label>
            <span id={`${radios}-password`} className="field-hint radio-hint">You pass it on to them; they can change it under Account.</span>
          </div>
          {withPassword && (
            <div className="stack-sm">
              <div className="grid-2">
                <Field label="Password" hint="At least 10 characters.">
                  <input
                    type={pwType}
                    required
                    minLength={10}
                    maxLength={200}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>
                <Field label="Confirm password" error={mismatch ? "The passwords don't match." : undefined}>
                  <input
                    id="new-user-confirm-password"
                    type={pwType}
                    required
                    minLength={10}
                    maxLength={200}
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>
              </div>
              <label className="checkbox">
                <input type="checkbox" checked={showPw} onChange={(e) => setShowPw(e.target.checked)} />
                Show password
              </label>
            </div>
          )}
        </fieldset>
        <label className="checkbox">
          <input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} />
          Make admin (can change settings and manage users)
        </label>
        <div>
          <Button type="submit" className="btn btn-primary" disabled={add.isPending || !email.trim()}>
            {add.isPending ? "Adding…" : withPassword ? "Add user" : "Add and create invite"}
          </Button>
        </div>
      </form>
      {add.error && <ResultNote ok={false}>{errorMessage(add.error)}</ResultNote>}
      {result && (
        <div className="stack-sm">
          {result.link === null ? (
            <ResultNote ok>
              Created an account for {result.user.email}
              {result.user.is_admin ? " (admin)" : ""} with the password you set. Pass the password on to them; they can sign in now and change it
              under Account.
            </ResultNote>
          ) : (
            <>
              <ResultNote ok>
                Created an account for {result.user.email}
                {result.user.is_admin ? " (admin)" : ""}.{" "}
                {result.emailed ? "They've been emailed a link to choose a password." : "Email isn't set up, so send them this link yourself."}
              </ResultNote>
              {!result.emailed && <CopyField label="Set-password link" value={result.link} hint="Valid for 24 hours, one use." />}
            </>
          )}
        </div>
      )}
    </section>
  );
}

/** Who can see or edit this user's plan; loaded when opened. */
function PlanAccess({ u }: { u: AdminUser }) {
  const [open, setOpen] = useState(false);
  const name = u.display_name || u.email;
  return (
    <details className="plan-access" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        Plan access<VisuallyHidden> for {name}</VisuallyHidden>
      </summary>
      {open && (
        <div className="plan-access-body">
          <PlanSharing target={{ kind: "user", id: u.id, name }} level={4} />
        </div>
      )}
    </details>
  );
}

function UserRow({ u, me }: { u: AdminUser; me: boolean }) {
  const qc = useQueryClient();
  const [link, setLink] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Toggles show the new state straight away; a refused change (e.g. last admin) snaps back.
  const [pending, setPending] = useState<{ is_admin?: boolean; is_active?: boolean }>({});
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-users"] });
  const update = useMutation({
    mutationFn: (changes: { is_admin?: boolean; is_active?: boolean }) => api.updateUser(u.id, changes),
    onMutate: () => setNote(null),
    onSettled: () => setPending({}),
    onSuccess: async () => {
      if (me) qc.invalidateQueries({ queryKey: ["me"] });
      await refresh(); // keep the pending toggle until the list has the new value
    },
  });
  // The checkboxes stay enabled while saving (disabling the focused one would drop focus); changes wait.
  const toggle = (changes: { is_admin?: boolean; is_active?: boolean }) => {
    if (busy) return;
    setPending(changes);
    update.mutate(changes);
  };
  const reset = useMutation({
    mutationFn: () => api.userResetLink(u.id),
    onMutate: () => setNote(null),
    onSuccess: (r) => setLink(r.link),
  });
  const signOut = useMutation({
    mutationFn: () => api.signOutUser(u.id),
    onMutate: () => setNote(null),
    onSuccess: () => setNote(`${u.email} was signed out on every device.`),
  });
  const announce = useAnnounce();
  const remove = useMutation({
    mutationFn: () => api.deleteUser(u.id),
    onSuccess: () => {
      refresh();
      announce(`Deleted ${u.email}.`);
      rescueFocus(() => document.getElementById("users-title"));
    },
  });
  const error = update.error || reset.error || signOut.error || remove.error;
  const busy = update.isPending || remove.isPending;

  return (
    <li className={`card stack-sm user-row ${u.is_active ? "" : "user-inactive"}`}>
      <div className="row between wrap">
        <div className="min-0">
          <h3 className="h-card break">{u.display_name || u.email}</h3>
          {u.display_name && <div className="muted small break">{u.email}</div>}
        </div>
        <div className="row wrap">
          {me && <span className="chip">you</span>}
          {u.is_admin && <span className="chip chip-ok">admin</span>}
          {!u.is_active && <span className="chip chip-off">deactivated</span>}
        </div>
      </div>
      <p className="muted small">
        Joined {when(u.created_at)} · last sign-in {when(u.last_login_at)} · {u.log_entries.toLocaleString()} log entr
        {u.log_entries === 1 ? "y" : "ies"}
      </p>
      <div className="row wrap">
        <label className="checkbox">
          <input type="checkbox" checked={pending.is_admin ?? u.is_admin} onChange={(e) => toggle({ is_admin: e.target.checked })} />
          Admin<VisuallyHidden> ({u.email})</VisuallyHidden>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={pending.is_active ?? u.is_active}
            disabled={me}
            onChange={(e) => {
              if (!e.target.checked && !confirm(`Deactivate ${u.email}? They are signed out and can't sign in until reactivated.`)) return;
              toggle({ is_active: e.target.checked });
            }}
          />
          Active<VisuallyHidden> ({u.email})</VisuallyHidden>
        </label>
      </div>
      <div className="row wrap">
        <Button type="button" className="btn btn-sm" onClick={() => reset.mutate()} disabled={reset.isPending}>
          {reset.isPending ? "Creating…" : "Reset link"}
          <VisuallyHidden> for {u.email}</VisuallyHidden>
        </Button>
        {!me && (
          <Button type="button" className="btn btn-sm" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
            Sign out everywhere<VisuallyHidden>({u.email})</VisuallyHidden>
          </Button>
        )}
        {!me && (
          <Button
            type="button"
            className="btn btn-sm danger"
            disabled={busy}
            onClick={() => {
              if (confirm(`Delete ${u.email} and all their data (log, recipes, own foods)? This can't be undone.`)) remove.mutate();
            }}
          >
            Delete<VisuallyHidden> {u.email}</VisuallyHidden>
          </Button>
        )}
      </div>
      {u.is_active && <PlanAccess u={u} />}
      {link && <CopyField label={`Password reset link for ${u.email}`} value={link} hint="Valid 24 h, one use. Creating another link cancels this one." />}
      {note && <ResultNote ok>{note}</ResultNote>}
      {error && <ResultNote ok={false}>{errorMessage(error)}</ResultNote>}
    </li>
  );
}

export default function AdminUsersPage() {
  const { user } = useAuth();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers, enabled: !!user?.is_admin });
  return (
    <AdminFrame intro={<p className="muted">Accounts on this server. There must always be at least one active admin.</p>}>
      <AddUserForm />
      {users.isLoading && <Loading />}
      <ErrorBox error={users.error} />
      {users.data && (
        <section className="stack-sm" aria-labelledby="users-title">
          <h2 id="users-title">
            Users <span className="muted small">({users.data.length})</span>
          </h2>
          <ul className="plain-list cards">
            {users.data.map((u) => (
              <UserRow key={u.id} u={u} me={u.id === user?.id} />
            ))}
          </ul>
        </section>
      )}
    </AdminFrame>
  );
}
