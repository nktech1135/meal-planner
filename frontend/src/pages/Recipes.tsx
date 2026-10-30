import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Loading, MacroLine } from "../components/common";
import { TrustBadge } from "../components/TrustBadge";
import { fmtNum } from "../lib";

export default function RecipesPage() {
  const recipes = useQuery({ queryKey: ["recipes"], queryFn: () => api.recipes() });
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Recipes</h1>
        <Link to="/recipes/new" className="btn btn-primary">
          + New recipe
        </Link>
      </div>
      <p className="muted">
        Weigh ingredients raw, cook, then weigh the finished dish. Setting the cooked weight lets you log portions by grams with the water lost (or
        gained) in cooking accounted for.
      </p>
      <ErrorBox error={recipes.error} />
      {recipes.isLoading && <Loading />}
      {recipes.data?.length === 0 && <p className="muted">No recipes yet.</p>}
      <ul className="plain-list cards">
        {recipes.data?.map((r) => {
          const n = r.nutrition && !("error" in r.nutrition) ? r.nutrition : null;
          return (
            <li key={r.id} className="card card-link">
              <Link to={`/recipes/${r.id}`}>
                <div className="row between">
                  <strong>{r.name}</strong>
                  {n && <TrustBadge level={n.trust_level} />}
                </div>
                <div className="small muted">
                  {r.ingredients.length} ingredients · {fmtNum(r.servings)} servings
                  {r.cooked_weight_g ? ` · ${fmtNum(r.cooked_weight_g)} g cooked` : ""}
                </div>
                {n && (
                  <div>
                    <span className="small muted">Per serving: </span>
                    <MacroLine values={n.per_serving} />
                  </div>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
