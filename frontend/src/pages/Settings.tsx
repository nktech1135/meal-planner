import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading, ResultNote } from "../components/common";
import type { Integration, SettingRow, SettingValue } from "../types";

/** Which integration test sits next to which setting (the last credential of a pair). */
const TESTS: Record<string, { integration: Integration; label: string }> = {
  anthropic_api_key: { integration: "anthropic", label: "Test Anthropic" },
  usda_fdc_api_key: { integration: "usda_fdc", label: "Test USDA" },
  nutritionix_app_key: { integration: "nutritionix", label: "Test Nutritionix" },
  edamam_app_key: { integration: "edamam", label: "Test Edamam" },
};

function SourceNote({ row }: { row: SettingRow }) {
  if (row.source === "environment") return <span className="muted small source-note">from server environment</span>;
  if (row.source === "default" && row.kind !== "secret") return <span className="muted small source-note">default</span>;
  return null;
}

function TestButton({ integration, label }: { integration: Integration; label: string }) {
  const test = useMutation({ mutationFn: () => api.testIntegration(integration) });
  return (
    <div className="stack-sm">
      <div>
        <button type="button" className="btn btn-sm" onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? "Testing…" : label}
        </button>
      </div>
      {test.data && <ResultNote ok={test.data.ok}>{test.data.message}</ResultNote>}
      {test.error && <ResultNote ok={false}>{errorMessage(test.error)}</ResultNote>}
    </div>
  );
}

function SettingItem({ row }: { row: SettingRow }) {
  const qc = useQueryClient();
  const [secret, setSecret] = useState("");
  const [num, setNum] = useState(row.kind === "int" || row.kind === "string" ? String(row.value ?? "") : "");
  const [saved, setSaved] = useState<string | null>(null);
  // Toggles and selects show the new value straight away while it saves.
  const [optimistic, setOptimistic] = useState<SettingValue | undefined>(undefined);
  const save = useMutation({
    mutationFn: (value: SettingValue) => api.saveAdminSettings({ [row.key]: value }),
    onSuccess: (rows, value) => {
      qc.setQueryData(["admin-settings"], rows);
      qc.invalidateQueries({ queryKey: ["app-info"] });
      qc.invalidateQueries({ queryKey: ["sources"] });
      const updated = rows.find((r) => r.key === row.key);
      if ((row.kind === "int" || row.kind === "string") && updated) setNum(String(updated.value ?? ""));
      setSecret("");
      setSaved(value === null ? (row.kind === "secret" ? "Removed." : "Reset to default.") : "Saved.");
    },
    onMutate: () => setSaved(null),
    onSettled: () => setOptimistic(undefined),
  });
  const change = (value: SettingValue) => {
    setOptimistic(value);
    save.mutate(value);
  };
  const shown = optimistic !== undefined ? optimistic : row.value;
  const id = `setting-${row.key}`;
  const descId = `${id}-desc`;
  const test = TESTS[row.key];

  function submitSecret(e: FormEvent) {
    e.preventDefault();
    if (secret.trim()) save.mutate(secret.trim());
  }
  function submitNum(e: FormEvent) {
    e.preventDefault();
    const n = Number(num);
    if (num.trim() !== "" && Number.isInteger(n)) save.mutate(n);
  }

  const description = (row.description || row.link) && (
    <p id={descId} className="muted small setting-desc">
      {row.description}{" "}
      {row.link && (
        <a href={row.link} target="_blank" rel="noopener noreferrer">
          {row.kind === "secret" ? (row.description.startsWith("Free") ? "Get a free key" : "Get a key") : "More info"} ↗
        </a>
      )}
    </p>
  );

  return (
    <div className="setting">
      {row.kind === "bool" ? (
        <div className="setting-head">
          <label className="checkbox setting-toggle" htmlFor={id}>
            <input
              id={id}
              type="checkbox"
              checked={shown === true}
              disabled={save.isPending}
              aria-describedby={descId}
              onChange={(e) => change(e.target.checked)}
            />
            <strong>{row.label}</strong>
          </label>
          <SourceNote row={row} />
        </div>
      ) : (
        <div className="setting-head">
          <label htmlFor={id}>
            <strong>{row.label}</strong>
          </label>
          {row.kind === "secret" && (
            <span className={`chip ${row.is_set ? "chip-ok" : "chip-off"}`}>
              {row.is_set ? `Set (${row.value ?? "••••"})` : "Not set"}
            </span>
          )}
          <SourceNote row={row} />
        </div>
      )}
      {description}

      {row.kind === "secret" && (
        <form className="row wrap" onSubmit={submitSecret}>
          <input
            id={id}
            name={row.key}
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="grow"
            placeholder={row.is_set ? "Enter a new value to replace it" : "Paste the value"}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            aria-describedby={descId}
          />
          <button type="submit" className="btn btn-primary btn-sm" disabled={!secret.trim() || save.isPending}>
            Save
          </button>
          {row.source === "settings" && (
            <button
              type="button"
              className="btn btn-sm danger"
              disabled={save.isPending}
              onClick={() => {
                if (confirm(`Remove the stored ${row.label}?`)) save.mutate(null);
              }}
            >
              Remove
            </button>
          )}
        </form>
      )}

      {row.kind === "choice" && (
        <div className="row wrap">
          <select id={id} value={String(shown ?? "")} disabled={save.isPending} onChange={(e) => change(e.target.value)} aria-describedby={descId}>
            {row.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      {row.kind === "int" && (
        <form className="row wrap" onSubmit={submitNum}>
          <input
            id={id}
            type="number"
            inputMode="numeric"
            step="1"
            min={row.minimum ?? undefined}
            max={row.maximum ?? undefined}
            className="w-sm"
            value={num}
            onChange={(e) => setNum(e.target.value)}
            aria-describedby={descId}
          />
          <button type="submit" className="btn btn-sm" disabled={save.isPending || num === String(row.value ?? "")}>
            Save
          </button>
          {row.minimum !== null && row.maximum !== null && (
            <span className="muted small">
              {row.minimum}–{row.maximum}
            </span>
          )}
        </form>
      )}

      {row.kind === "string" && (
        <form
          className="row wrap"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(num.trim() || null);
          }}
        >
          <input id={id} className="grow" value={num} onChange={(e) => setNum(e.target.value)} aria-describedby={descId} />
          <button type="submit" className="btn btn-sm" disabled={save.isPending}>
            Save
          </button>
        </form>
      )}

      {row.kind !== "secret" && row.source === "settings" && (
        <div>
          <button type="button" className="btn-link small" disabled={save.isPending} onClick={() => save.mutate(null)}>
            Reset to {row.kind === "bool" || row.kind === "choice" || row.kind === "int" ? "server default" : "default"}
          </button>
        </div>
      )}

      {save.error && <ResultNote ok={false}>{errorMessage(save.error)}</ResultNote>}
      {saved && !save.error && (
        <p className="muted small" role="status">
          {saved}
        </p>
      )}
      {test && <TestButton integration={test.integration} label={test.label} />}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: api.adminSettings, enabled: !!user?.is_admin });

  if (!user?.is_admin) {
    return (
      <div className="stack">
        <h1>Settings</h1>
        <div className="alert alert-info">Only admins can change app settings.</div>
      </div>
    );
  }
  if (settings.isLoading) return <Loading />;
  if (!settings.data) return <ErrorBox error={settings.error} />;

  const groups: string[] = [];
  for (const r of settings.data) if (!groups.includes(r.group)) groups.push(r.group);

  return (
    <div className="stack">
      <div>
        <h1>Settings</h1>
        <p className="muted">
          App-wide settings and API keys. Values saved here override the server environment. Keys are stored encrypted and only the last four
          characters are ever shown.
        </p>
      </div>
      {groups.map((g) => (
        <section key={g} className="card stack" aria-labelledby={`group-${g}`}>
          <h2 id={`group-${g}`}>{g}</h2>
          {settings.data
            .filter((r) => r.group === g)
            .map((r) => (
              <SettingItem key={r.key} row={r} />
            ))}
        </section>
      ))}
    </div>
  );
}
