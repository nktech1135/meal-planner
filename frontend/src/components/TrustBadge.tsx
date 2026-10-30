import type { Trust } from "../types";

export const TRUST_INFO: Record<Trust, { label: string; icon: string; description: string }> = {
  analytical: {
    label: "Analytical",
    icon: "✓",
    description: "Government lab-analysed or compiled data (USDA Foundation, SR Legacy, FNDDS).",
  },
  label: {
    label: "Label",
    icon: "▤",
    description: "Manufacturer label declarations catalogued by a government database (USDA Branded, NIH DSLD). Not independently tested.",
  },
  commercial: {
    label: "Commercial",
    icon: "◆",
    description: "Licensed commercial nutrition database (Nutritionix, Edamam).",
  },
  user: {
    label: "User",
    icon: "✎",
    description: "Entered by hand by a user. Only as reliable as its source.",
  },
  unverified: {
    label: "Unverified",
    icon: "⚠",
    description: "Crowdsourced data that anyone can edit. Not verified against a lab or label.",
  },
};

export function TrustBadge({ level, compact = false }: { level: Trust | string | null | undefined; compact?: boolean }) {
  const key = (level ?? "user") as Trust;
  const info = TRUST_INFO[key] ?? TRUST_INFO.user;
  return (
    <span className={`trust trust-${key}`} title={`${info.label}: ${info.description}`}>
      <span aria-hidden="true">{info.icon}</span>
      {compact ? <span className="sr-only">{info.label}</span> : <span>{info.label}</span>}
    </span>
  );
}

export function TrustLegend() {
  return (
    <details className="legend">
      <summary>What do the data-trust badges mean?</summary>
      <dl>
        {(Object.keys(TRUST_INFO) as Trust[]).map((t) => (
          <div key={t} className="legend-row">
            <dt>
              <TrustBadge level={t} />
            </dt>
            <dd>{TRUST_INFO[t].description}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
