import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api";
import { useAuth } from "../auth";
import { AdminFrame } from "../components/AdminTabs";
import { ErrorBox, Loading, ResultNote } from "../components/common";
import type { Dataset, ImportJob } from "../types";
import { Button, NewTab, useAnnounceWhen, VisuallyHidden } from "../components/a11y";

const ORDER = [
  "fdc_sr_legacy", "fdc_foundation", "fdc_survey", "usda_retention", "fdc_branded",
  "intl_cofid", "intl_cnf", "intl_afcd", "intl_bls", "intl_ciqual", "intl_dk_fcdb", "intl_fineli",
  "intl_matvaretabellen", "intl_se_livsmedel", "intl_swiss",
];
const active = (j: ImportJob | null | undefined) => !!j && (j.status === "queued" || j.status === "running");

/**
 * Polls a queued/running job every 1.5 s until it finishes. Screen readers hear the state changes
 * (queued, importing, done/failed), not every progress tick; the progress bar can be read any time.
 */
function JobProgress({ job: initial, label }: { job: ImportJob; label: string }) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: ["job", initial.id],
    queryFn: () => api.job(initial.id),
    initialData: initial,
    refetchInterval: (q) => (active(q.state.data) ? 1500 : false),
  });
  const j = job.data;
  const finished = !active(j);
  useEffect(() => {
    if (finished) {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["foods"] });
    }
  }, [finished, qc]);

  useAnnounceWhen(j.status === "queued" ? `${label}: import queued.` : j.status === "running" ? `${label}: importing.` : null);

  if (j.status === "failed")
    return (
      <ResultNote ok={false}>
        {label}: {j.message || "The import failed."}
      </ResultNote>
    );
  if (j.status === "done")
    return (
      <ResultNote ok>
        {label}: {j.message || "Import finished."}
      </ResultNote>
    );
  const pct = j.total ? Math.min(100, Math.round((j.progress / j.total) * 100)) : null;
  return (
    <div className="job">
      <div className="row between wrap small">
        <span>
          <span className="spinner" aria-hidden="true" /> {j.status === "queued" ? "Queued" : "Importing"}: {j.message || "working…"}
        </span>
        {j.total ? (
          <span className="muted nowrap">
            {j.progress.toLocaleString()} of {j.total.toLocaleString()} ({pct}%)
          </span>
        ) : null}
      </div>
      {pct !== null && (
        <div
          className="bar job-bar"
          role="progressbar"
          aria-label={`${label} import progress`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-valuetext={`${pct}%, ${j.progress.toLocaleString()} of ${j.total!.toLocaleString()}`}
        >
          <div className="bar-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
      <ErrorBox error={job.error} />
    </div>
  );
}

function DatasetCard({ ds, busy }: { ds: Dataset; busy: boolean }) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: () => api.importDataset(ds.key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
  const running = active(ds.last_job);
  const action = !ds.imported_release
    ? "Import"
    : ds.update_available && ds.available_release
      ? `Update to ${ds.available_release}`
      : "Re-import";
  const lastFinished = ds.last_job && !running ? ds.last_job : null;

  return (
    <li className="card stack-sm dataset">
      <div className="row between wrap">
        <h3 className="h-card">{ds.label}</h3>
        {ds.imported_release ? (
          ds.update_available ? (
            <span className="chip chip-warn">Update available</span>
          ) : (
            <span className="chip chip-ok">
              <span aria-hidden="true">✓ </span>Up to date
            </span>
          )
        ) : (
          <span className="chip chip-off">Not imported</span>
        )}
      </div>
      <p className="small">{ds.description}</p>
      <dl className="kv small">
        <dt>Records on file</dt>
        <dd>{ds.records.toLocaleString()}</dd>
        <dt>Imported release</dt>
        <dd>{ds.imported_release ?? "—"}</dd>
        <dt>Available release</dt>
        <dd>{ds.available_release ?? "unknown"}</dd>
        <dt>Download</dt>
        <dd>{ds.size}</dd>
        <dt>Licence</dt>
        <dd>
          {ds.licence_url ? (
            <a href={ds.licence_url} target="_blank" rel="noopener noreferrer">
              {ds.licence}
              <NewTab />
            </a>
          ) : (
            ds.licence
          )}
        </dd>
      </dl>
      {ds.attribution && <p className="muted small">{ds.attribution}</p>}
      {running && ds.last_job && <JobProgress job={ds.last_job} label={ds.label} />}
      {start.data && !running && start.data.id !== ds.last_job?.id && <JobProgress job={start.data} label={ds.label} />}
      {lastFinished?.status === "failed" && <ResultNote ok={false}>Last import failed: {lastFinished.message}</ResultNote>}
      {lastFinished?.status === "done" && lastFinished.finished_at && (
        <p className="muted small">
          Last import finished {new Date(lastFinished.finished_at).toLocaleString()}
          {lastFinished.message ? ` — ${lastFinished.message}` : ""}
        </p>
      )}
      {start.error && <ResultNote ok={false}>{errorMessage(start.error)}</ResultNote>}
      <div>
        <Button
          type="button"
          className={`btn ${ds.imported_release && !ds.update_available ? "" : "btn-primary"}`}
          disabled={running || busy || start.isPending}
          onClick={() => {
            if (ds.imported_release && !ds.update_available && !confirm(`Re-import ${ds.label}? Existing records are updated in place.`)) return;
            start.mutate();
          }}
        >
          {start.isPending ? "Starting…" : running ? "Importing…" : action}
          <VisuallyHidden> {ds.label}</VisuallyHidden>
        </Button>
      </div>
    </li>
  );
}

export default function AdminDataPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
    enabled: !!user?.is_admin,
    staleTime: 0,
  });
  const derive = useMutation({
    mutationFn: api.deriveYields,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yields"] }),
  });
  const list = [...(datasets.data ?? [])].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  const anyRunning = list.some((d) => active(d.last_job));

  return (
    <AdminFrame
      intro={
        <p className="muted">
          Reference food databases from government and research agencies, imported into this server so everyone can search them offline.
          Imports run in the background; you can leave this page. Each database's licence and required credit are shown on its card and on
          the <Link to="/about/data">Data sources & credits</Link> page.
        </p>
      }
    >
      <div className="alert alert-info small">
        <strong>Suggested order:</strong> SR Legacy, then Foundation, then Survey (FNDDS), then Retention factors. After each food import about
        1,000 cooking yields are derived automatically from USDA raw/cooked pairs (e.g. “Beef, raw” and “Beef, roasted”), so people can log food
        weighed after cooking.
      </div>
      {datasets.isLoading && <Loading what="Checking datasets" />}
      <ErrorBox error={datasets.error} />
      <h2 className="h-sm">United States</h2>
      <ul className="plain-list cards dataset-grid">
        {list.filter((d) => d.country === "United States").map((d) => (
          <DatasetCard key={d.key} ds={d} busy={anyRunning} />
        ))}
      </ul>
      <h2 className="h-sm">Other countries</h2>
      <p className="muted small">
        Free national databases with open licences. They add foods sold or cooked in those countries; people who don't want them in search
        results can hide them in their Profile.
      </p>
      <ul className="plain-list cards dataset-grid">
        {list.filter((d) => d.country !== "United States").map((d) => (
          <DatasetCard key={d.key} ds={d} busy={anyRunning} />
        ))}
      </ul>
      <section className="card stack-sm" aria-labelledby="derive-title">
        <h2 id="derive-title">Cooking yields from USDA pairs</h2>
        <p className="muted small">
          Matches raw and cooked USDA entries of the same food and derives a yield for each pair. This runs after every food import; run it again
          if yields were deleted or after changing data by hand.
        </p>
        <div>
          <Button type="button" className="btn" onClick={() => derive.mutate()} disabled={derive.isPending || anyRunning}>
            {derive.isPending ? "Deriving…" : "Re-derive cooking yields"}
          </Button>
        </div>
        {derive.data && <ResultNote ok>{derive.data.yields.toLocaleString()} cooking yields derived.</ResultNote>}
        {derive.error && <ResultNote ok={false}>{errorMessage(derive.error)}</ResultNote>}
      </section>
    </AdminFrame>
  );
}
