import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { AdminFrame } from "../components/AdminTabs";
import { ErrorBox, Loading, ResultNote } from "../components/common";
import { useAppInfo } from "../lib";
import type { Integration, SettingRow, SettingValue } from "../types";
import { Button, NewTab, useAnnounce, VisuallyHidden } from "../components/a11y";

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
        <Button type="button" className="btn btn-sm" onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? "Testing…" : label}
        </Button>
      </div>
      {test.data && <ResultNote ok={test.data.ok}>{test.data.message}</ResultNote>}
      {test.error && <ResultNote ok={false}>{errorMessage(test.error)}</ResultNote>}
    </div>
  );
}

function TestEmail() {
  const { user } = useAuth();
  const info = useAppInfo();
  const test = useMutation({ mutationFn: api.testEmail });
  return (
    <div className="setting">
      <strong>Check the email settings</strong>
      <p className="muted small setting-desc">
        {info?.email_enabled
          ? `Sends a test message to your address (${user?.email}).`
          : "Email isn't fully set up yet (it needs at least the SMTP server and a From address). Until then, password resets work with links you create under Users."}
      </p>
      <div>
        <Button type="button" className="btn btn-sm" onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? "Sending…" : "Send test email"}
        </Button>
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
  const announce = useAnnounce();
  const save = useMutation({
    mutationFn: (value: SettingValue) => api.saveAdminSettings({ [row.key]: value }),
    onSuccess: (rows, value) => {
      qc.setQueryData(["admin-settings"], rows);
      qc.invalidateQueries({ queryKey: ["app-info"] });
      qc.invalidateQueries({ queryKey: ["sources"] });
      const updated = rows.find((r) => r.key === row.key);
      if ((row.kind === "int" || row.kind === "string") && updated) setNum(String(updated.value ?? ""));
      setSecret("");
      const msg = value === null ? (row.kind === "secret" ? "Removed." : "Reset to default.") : "Saved.";
      setSaved(msg);
      announce(`${row.label}: ${msg}`);
    },
    onMutate: () => setSaved(null),
    onSettled: () => setOptimistic(undefined),
  });
  // Toggles and selects stay enabled while saving (disabling the focused control would drop focus);
  // a change made meanwhile is ignored.
  const change = (value: SettingValue) => {
    if (save.isPending) return;
    setOptimistic(value);
    save.mutate(value);
  };
  const shown = optimistic !== undefined ? optimistic : row.value;
  const id = `setting-${row.key}`;
  const descId = `${id}-desc`;
  const errorId = `${id}-error`;
  const hasDesc = !!(row.description || row.link);
  const describedBy = [hasDesc && descId, save.error && errorId].filter(Boolean).join(" ") || undefined;
  const invalid = save.error ? true : undefined;
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
          {row.kind === "secret" ? (row.description.startsWith("Free") ? "Get a free key" : "Get a key") : "More info"}
          <VisuallyHidden> for {row.label}</VisuallyHidden>
          <NewTab />
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
              aria-describedby={describedBy}
              aria-invalid={invalid}
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
              {row.is_set ? (
                <>
                  <span aria-hidden="true">Set ({row.value ?? "••••"})</span>
                  <VisuallyHidden>
                    Set{typeof row.value === "string" && /[^•]/.test(row.value) ? `, ending in ${row.value.replace(/•/g, "")}` : ""}
                  </VisuallyHidden>
                </>
              ) : (
                "Not set"
              )}
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
            aria-describedby={describedBy}
            aria-invalid={invalid}
          />
          <Button type="submit" className="btn btn-primary btn-sm" disabled={!secret.trim() || save.isPending}>
            Save<VisuallyHidden> {row.label}</VisuallyHidden>
          </Button>
          {row.source === "settings" && (
            <Button
              type="button"
              className="btn btn-sm danger"
              disabled={save.isPending}
              onClick={() => {
                if (confirm(`Remove the stored ${row.label}?`)) save.mutate(null);
              }}
            >
              Remove<VisuallyHidden> {row.label}</VisuallyHidden>
            </Button>
          )}
        </form>
      )}

      {row.kind === "choice" && (
        <div className="row wrap">
          <select id={id} value={String(shown ?? "")} onChange={(e) => change(e.target.value)} aria-describedby={describedBy} aria-invalid={invalid}>
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
            aria-describedby={describedBy}
            aria-invalid={invalid}
          />
          <Button type="submit" className="btn btn-sm" disabled={save.isPending || num === String(row.value ?? "")}>
            Save<VisuallyHidden> {row.label}</VisuallyHidden>
          </Button>
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
          <input
            id={id}
            type="text"
            className="grow"
            value={num}
            maxLength={500}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setNum(e.target.value)}
            aria-describedby={describedBy}
            aria-invalid={invalid}
          />
          <Button type="submit" className="btn btn-sm" disabled={save.isPending || num.trim() === String(row.value ?? "")}>
            Save<VisuallyHidden> {row.label}</VisuallyHidden>
          </Button>
        </form>
      )}

      {row.kind !== "secret" && row.source === "settings" && (
        <div>
          <Button type="button" className="btn-link small" disabled={save.isPending} onClick={() => save.mutate(null)}>
            Reset to {row.kind === "bool" || row.kind === "choice" || row.kind === "int" ? "server default" : "default"}
            <VisuallyHidden>for {row.label}</VisuallyHidden>
          </Button>
        </div>
      )}

      {save.error && (
        <ResultNote ok={false} id={errorId}>
          {errorMessage(save.error)}
        </ResultNote>
      )}
      {saved && !save.error && <p className="muted small">{saved}</p>}
      {test && <TestButton integration={test.integration} label={test.label} />}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: api.adminSettings, enabled: !!user?.is_admin });

  const groups: string[] = [];
  for (const r of settings.data ?? []) if (!groups.includes(r.group)) groups.push(r.group);

  return (
    <AdminFrame
      intro={
        <p className="muted">
          App-wide settings and API keys. Values saved here override the server environment. Keys and passwords are stored encrypted and only the
          last four characters are ever shown.
        </p>
      }
    >
      {settings.isLoading && <Loading />}
      <ErrorBox error={settings.error} />
      {groups.map((g, gi) => (
        <section key={g} className="card stack" aria-labelledby={`settings-group-${gi}`}>
          <h2 id={`settings-group-${gi}`}>{g}</h2>
          {settings.data!
            .filter((r) => r.group === g)
            .map((r) => (
              <SettingItem key={r.key} row={r} />
            ))}
          {g === "Email" && <TestEmail />}
        </section>
      ))}
    </AdminFrame>
  );
}
