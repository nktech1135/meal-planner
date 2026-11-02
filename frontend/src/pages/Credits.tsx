import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Loading } from "../components/common";
import { NewTab } from "../components/a11y";

/** Every reference database the server can hold, with the credit its licence requires. */
export default function CreditsPage() {
  const dbs = useQuery({ queryKey: ["food-databases"], queryFn: api.foodDatabases });
  return (
    <div className="stack">
      <h1>Data sources & credits</h1>
      <p className="muted">
        Food composition data in this app comes from these public databases. Each is used under the licence shown, and each food records its
        own source and citation. Supplement label data comes from the NIH Dietary Supplement Label Database (U.S. government, public).
      </p>
      {dbs.isLoading && <Loading what="Loading sources" />}
      <ErrorBox error={dbs.error} />
      <ul className="plain-list stack">
        {(dbs.data ?? []).map((d) => (
          <li key={d.source} className="card stack-sm">
            <div className="row between wrap">
              <h2 className="h-card">{d.label}</h2>
              <span className="muted small">{d.country}</span>
            </div>
            <p className="small">{d.attribution}</p>
            <p className="muted small">
              Licence:{" "}
              {d.licence_url ? (
                <a href={d.licence_url} target="_blank" rel="noopener noreferrer">
                  {d.licence}
                  <NewTab />
                </a>
              ) : (
                d.licence
              )}
              {" · "}
              {d.records > 0 ? `${d.records.toLocaleString()} foods on this server` : "not imported on this server"}
            </p>
          </li>
        ))}
      </ul>
      <h2>Research</h2>
      <ul className="plain-list stack">
        <li className="card stack-sm">
          <h3 className="h-card">PubMed</h3>
          <p className="small">
            The advisor can search PubMed, from the U.S. National Library of Medicine, through NCBI's E-utilities. Abstracts remain their publishers'.
          </p>
          <p className="muted small">
            <a href="https://www.ncbi.nlm.nih.gov/home/about/policies/" target="_blank" rel="noopener noreferrer">
              NCBI policies
              <NewTab />
            </a>
          </p>
        </li>
      </ul>
    </div>
  );
}
