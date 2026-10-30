import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, ResultNote } from "../components/common";
import { useAppInfo } from "../lib";

function ForgotPassword({ initialEmail, onBack }: { initialEmail: string; onBack: () => void }) {
  const [email, setEmail] = useState(initialEmail);
  const [result, setResult] = useState<{ email_enabled: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.forgotPassword(email.trim()));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack">
      <h2>Reset your password</h2>
      {result ? (
        result.email_enabled ? (
          <ResultNote ok>If an account exists for {email.trim()}, we've emailed a link to choose a new password. It's valid for 24 hours.</ResultNote>
        ) : (
          <div className="alert alert-info" role="status">
            Email isn't set up on this server, so no link could be sent. Ask an admin for a reset link (Settings → Users → Reset link).
          </div>
        )
      ) : (
        <form onSubmit={submit} className="stack">
          <Field label="Email">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus />
          </Field>
          <ErrorBox error={error} />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Please wait…" : "Send reset link"}
          </button>
        </form>
      )}
      <div>
        <button type="button" className="btn-link" onClick={onBack}>
          ← Back to sign in
        </button>
      </div>
    </div>
  );
}

export default function LoginPage() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [forgot, setForgot] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const info = useAppInfo();
  const [firstAccount, setFirstAccount] = useState(false);
  // The very first account can always be created (it becomes the admin); the server says so if it can't.
  const closed = mode === "register" && info?.allow_registration === false && !firstAccount;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = mode === "login" ? await api.login(email, password) : await api.register(email, password, name);
      setUser(user);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container narrow">
      <div className="card auth-card">
        <h1>Mealplan</h1>
        <p className="muted">Track meals and supplements, with every number traced to its source.</p>
        {forgot ? (
          <ForgotPassword initialEmail={email} onBack={() => setForgot(false)} />
        ) : (
          <>
            <div className="tabs" role="tablist">
              <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
                Sign in
              </button>
              <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>
                Create account
              </button>
            </div>
            {closed ? (
              <div className="stack">
                <div className="alert alert-info" role="status">
                  Sign-ups are closed; ask an admin for an account.
                </div>
                <p className="muted small">
                  Setting up a brand-new server?{" "}
                  <button type="button" className="btn-link" onClick={() => setFirstAccount(true)}>
                    Create the first (admin) account
                  </button>
                </p>
              </div>
            ) : (
              <form onSubmit={submit} className="stack">
                {mode === "register" && (
                  <Field label="Display name">
                    <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="nickname" />
                  </Field>
                )}
                <Field label="Email">
                  <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
                </Field>
                <Field label="Password" hint={mode === "register" ? "At least 10 characters." : undefined}>
                  <input
                    type="password"
                    required
                    minLength={mode === "register" ? 10 : undefined}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                  />
                </Field>
                <ErrorBox error={error} />
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
                </button>
                {mode === "login" && (
                  <div>
                    <button type="button" className="btn-link small" onClick={() => setForgot(true)}>
                      Forgot password?
                    </button>
                  </div>
                )}
              </form>
            )}
          </>
        )}
      </div>
    </main>
  );
}
