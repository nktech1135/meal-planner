import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { Field, ResultNote } from "../components/common";
import { Button, focusSoon, useReturnFocus } from "../components/a11y";
import { Sharing } from "../components/Sharing";
import { activeProfile, clearProfile } from "../profile";

function DetailsForm() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const emailChanged = email.trim().toLowerCase() !== (user?.email ?? "");
  const save = useMutation({
    mutationFn: () => api.updateAccount({ display_name: name.trim(), email: email.trim(), current_password: emailChanged ? password : null }),
    onSuccess: (u) => {
      // Same user, so keep the cache; just refresh "me".
      qc.setQueryData(["me"], u);
      setPassword("");
      setEmail(u.email);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <section className="card stack" aria-labelledby="details-title">
      <h2 id="details-title">Your details</h2>
      <form className="stack-sm" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Display name">
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoComplete="nickname" />
          </Field>
          <Field label="Email">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
        </div>
        {emailChanged && (
          <Field label="Current password" hint="Needed to change your email.">
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
        )}
        <div className="row wrap">
          <Button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save details"}
          </Button>
        </div>
        {save.isSuccess && <ResultNote ok>Saved.</ResultNote>}
        {save.error && <ResultNote ok={false}>{errorMessage(save.error)}</ResultNote>}
      </form>
    </section>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const mismatch = (confirmPw !== "" || submitted) && next !== confirmPw;
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirmPw("");
      setSubmitted(false);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    // Required/length checks are the browser's; the match check is ours: say so and go to the field.
    if (next !== confirmPw) focusSoon(() => document.getElementById("confirm-new-password"));
    else if (next.length >= 10) change.mutate();
  }
  return (
    <section className="card stack" aria-labelledby="password-title">
      <h2 id="password-title">Change password</h2>
      <form className="stack-sm" onSubmit={submit}>
        <Field label="Current password">
          <input type="password" required value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        </Field>
        <div className="grid-2">
          <Field label="New password" hint="At least 10 characters.">
            <input type="password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
          </Field>
          <Field label="Confirm new password" error={mismatch ? "The passwords don't match." : undefined}>
            <input
              id="confirm-new-password"
              type="password"
              required
              minLength={10}
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
        </div>
        <div>
          <Button type="submit" className="btn btn-primary" disabled={change.isPending}>
            {change.isPending ? "Changing…" : "Change password"}
          </Button>
        </div>
        {change.isSuccess && <ResultNote ok>Password changed. You've been signed out on your other devices.</ResultNote>}
        {change.error && <ResultNote ok={false}>{errorMessage(change.error)}</ResultNote>}
      </form>
    </section>
  );
}

function ExportData() {
  const exp = useMutation({ mutationFn: api.exportData });
  return (
    <section className="card stack-sm" aria-labelledby="export-title">
      <h2 id="export-title">Download my data</h2>
      <p className="muted small">
        One JSON file with your profile, log, recipes, your own foods, saved meals, meal plan, body measurements and advisor conversations.
      </p>
      <div>
        <Button type="button" className="btn" onClick={() => exp.mutate()} disabled={exp.isPending}>
          {exp.isPending ? "Preparing…" : "Download my data"}
        </Button>
      </div>
      {exp.isSuccess && <ResultNote ok>Download started.</ResultNote>}
      {exp.error && <ResultNote ok={false}>{errorMessage(exp.error)}</ResultNote>}
    </section>
  );
}

function DeleteAccount() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const openButton = useReturnFocus<HTMLButtonElement>(open);
  const [password, setPassword] = useState("");
  const remove = useMutation({
    mutationFn: () => api.deleteAccount(password),
    onSuccess: () => {
      clearProfile();
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], null);
      navigate("/", { replace: true });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (password && confirm("Permanently delete your account and all your data? This can't be undone.")) remove.mutate();
  }
  return (
    <section className="card stack-sm danger-zone" aria-labelledby="delete-title">
      <h2 id="delete-title">Danger zone</h2>
      <p className="small">
        Deleting your account removes your log, recipes, own foods, plan and conversations for good. Download your data first if you want a copy.
      </p>
      {open ? (
        <form className="stack-sm" onSubmit={submit}>
          <Field label="Your password">
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
          </Field>
          <div className="row wrap">
            <Button type="submit" className="btn btn-danger" disabled={!password || remove.isPending}>
              {remove.isPending ? "Deleting…" : "Delete my account"}
            </Button>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
          {remove.error && <ResultNote ok={false}>{errorMessage(remove.error)}</ResultNote>}
        </form>
      ) : (
        <div>
          <button ref={openButton} type="button" className="btn danger" onClick={() => setOpen(true)}>
            Delete my account…
          </button>
        </div>
      )}
    </section>
  );
}

function ProfileSharing() {
  return (
    <section className="card stack" aria-labelledby="profile-sharing-title">
      <div>
        <h2 id="profile-sharing-title">Share your profile</h2>
        <p className="muted small">
          Give someone you trust, such as a partner, carer or coach, access to all of your data, or see only. People
          who share theirs with you appear under the Me menu, where you can switch to their profile.
        </p>
      </div>
      <Sharing scope="profile" target={{ kind: "mine" }} level={3} />
    </section>
  );
}

export default function AccountPage() {
  const { user } = useAuth();
  const using = activeProfile();
  return (
    <div className="stack">
      <div>
        <h1>Account</h1>
        <p className="muted">
          Signed in as {user?.email}
          {user?.is_admin ? " (admin)" : ""}.
        </p>
      </div>
      {using && (
        <p className="alert alert-info" role="note">
          This is your own account. You're using {using.name}'s profile in the rest of the app; their account stays theirs.
        </p>
      )}
      <DetailsForm />
      <ProfileSharing />
      <PasswordForm />
      <ExportData />
      <DeleteAccount />
    </div>
  );
}
