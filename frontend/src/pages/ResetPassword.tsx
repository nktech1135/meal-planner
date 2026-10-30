import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field } from "../components/common";

/** Landing page for emailed / admin-made reset and invite links. Works signed out. */
export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { user: signedIn, setUser } = useAuth();
  const Wrap = signedIn ? "div" : "main"; // the signed-in app already provides <main>
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = confirmPw !== "" && password !== confirmPw;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 10 || password !== confirmPw) return;
    setBusy(true);
    setError(null);
    try {
      const user = await api.resetPassword(token, password);
      navigate("/", { replace: true });
      setUser(user);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Wrap className={signedIn ? "narrow-box" : "container narrow"}>
      <div className="card auth-card">
        <h1>Choose a password</h1>
        {!token ? (
          <>
            <div className="alert alert-error" role="alert">
              This link is missing its token. Open the full link from your email, or ask an admin for a new one.
            </div>
            <Link to="/">Go to sign in</Link>
          </>
        ) : (
          <form onSubmit={submit} className="stack">
            <p className="muted">Set a new password for your Mealplan account. You'll be signed in straight away.</p>
            <Field label="New password" hint="At least 10 characters.">
              <input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" autoFocus />
            </Field>
            <Field label="Confirm password" hint={mismatch ? <span className="warn-text">The passwords don't match.</span> : undefined}>
              <input
                type="password"
                required
                minLength={10}
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                autoComplete="new-password"
                aria-invalid={mismatch}
              />
            </Field>
            <ErrorBox error={error} />
            <button type="submit" className="btn btn-primary" disabled={busy || password.length < 10 || password !== confirmPw}>
              {busy ? "Saving…" : "Set password and sign in"}
            </button>
            <p className="small">
              <Link to="/">Back to sign in</Link>
            </p>
          </form>
        )}
      </div>
    </Wrap>
  );
}
