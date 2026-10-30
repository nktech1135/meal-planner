import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { AdminFrame } from "../components/AdminTabs";
import { CopyField, ErrorBox, Field, Loading, ResultNote } from "../components/common";
import type { AdminUser, InviteResult } from "../types";
import { Button, rescueFocus, useAnnounce, VisuallyHidden } from "../components/a11y";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }) : "never");

function InviteForm() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [result, setResult] = useState<InviteResult | null>(null);
  const invite = useMutation({
    mutationFn: () => api.inviteUser(email.trim(), name.trim()),
    onMutate: () => setResult(null),
    onSuccess: (r) => {
      setResult(r);
      setEmail("");
      setName("");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (email.trim()) invite.mutate();
  }
  return (
    <section className="card stack" aria-labelledby="invite-title">
      <h2 id="invite-title">Invite someone</h2>
      <p className="muted small">Creates the account (even with sign-ups closed) and a link for them to choose a password.</p>
      <form className="stack-sm" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Email">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Name (optional)">
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoComplete="off" />
          </Field>
        </div>
        <div>
          <Button type="submit" className="btn btn-primary" disabled={invite.isPending || !email.trim()}>
            {invite.isPending ? "Inviting…" : "Invite"}
          </Button>
        </div>
      </form>
      {invite.error && <ResultNote ok={false}>{errorMessage(invite.error)}</ResultNote>}
      {result && (
        <div className="stack-sm">
          <ResultNote ok>
            Created an account for {result.user.email}.{" "}
            {result.emailed ? "They've been emailed a link to choose a password." : "Email isn't set up, so send them this link yourself."}
          </ResultNote>
          {!result.emailed && <CopyField label="Set-password link" value={result.link} hint="Valid for 24 hours, one use." />}
        </div>
      )}
    </section>
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
      <InviteForm />
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
