import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field } from "../components/common";

export default function LoginPage() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

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
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>
            Create account
          </button>
        </div>
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
        </form>
      </div>
    </main>
  );
}
