"""Converting form-dependent label amounts (IU, plain µg) into RAE / α-tocopherol / DFE.

Factors from the NIH Office of Dietary Supplements health-professional fact sheets:
- Vitamin A: 1 IU retinol = 0.3 µg RAE; 1 IU supplemental β-carotene = 0.3 µg RAE;
  1 IU dietary β-carotene = 0.05 µg RAE. 1 µg retinol = 1 µg RAE; 2 µg supplemental
  β-carotene = 1 µg RAE.  https://ods.od.nih.gov/factsheets/VitaminA-HealthProfessional/
- Vitamin E: 1 IU natural (d-α-tocopherol, RRR) = 0.67 mg; 1 IU synthetic
  (dl-α-tocopherol, all-rac) = 0.45 mg.  https://ods.od.nih.gov/factsheets/VitaminE-HealthProfessional/
- Folate: 1 µg DFE = 0.6 µg folic acid taken with food; FDA labeling uses
  µg DFE = 1.7 × µg folic acid (21 CFR 101.9(c)(8)(iv)).
  https://ods.od.nih.gov/factsheets/Folate-HealthProfessional/
"""

from dataclasses import dataclass

from app.nutrients import normalize_unit

ODS_A = "https://ods.od.nih.gov/factsheets/VitaminA-HealthProfessional/"
ODS_E = "https://ods.od.nih.gov/factsheets/VitaminE-HealthProfessional/"
ODS_FOLATE = "https://ods.od.nih.gov/factsheets/Folate-HealthProfessional/"


@dataclass(frozen=True)
class FormOption:
    key: str
    label: str
    factor: float  # multiply the declared amount by this to get the canonical unit
    source: str
    patterns: tuple[str, ...] = ()  # lowercase substrings that identify this form on a label
    note: str = ""


_RETINOL = ("retinyl", "retinol", "vitamin a acetate", "vitamin a palmitate")
_BETA_CAROTENE = ("beta-carotene", "beta carotene", "β-carotene")

# (nutrient code, normalised unit) -> options
OPTIONS: dict[tuple[str, str], tuple[FormOption, ...]] = {
    ("vitamin_a_ug", "iu"): (
        FormOption("retinol", "Retinol / retinyl palmitate or acetate (preformed)", 0.3, ODS_A, _RETINOL),
        FormOption("beta_carotene_supplement", "Beta-carotene (supplement form)", 0.3, ODS_A, _BETA_CAROTENE,
                   "Beta-carotene doesn't count toward the vitamin A upper limit."),
        FormOption("carotenoids_food", "Carotenoids from food or plant concentrates", 0.05, ODS_A,
                   note="Uses the dietary beta-carotene factor; other carotenoids convert at half that."),
    ),
    ("vitamin_a_ug", "µg"): (
        FormOption("retinol", "Retinol / retinyl palmitate or acetate (preformed)", 1.0, ODS_A, _RETINOL),
        FormOption("beta_carotene_supplement", "Beta-carotene (supplement form)", 0.5, ODS_A, _BETA_CAROTENE),
    ),
    ("vitamin_e_mg", "iu"): (
        FormOption("natural", "Natural: d-alpha-tocopherol (RRR)", 0.67, ODS_E, ("d-alpha", "d alpha", "rrr")),
        FormOption("synthetic", "Synthetic: dl-alpha-tocopherol (all-rac)", 0.45, ODS_E, ("dl-alpha", "dl alpha", "all-rac")),
    ),
    ("folate_ug_dfe", "µg"): (
        FormOption("folic_acid", "Folic acid", 1.7, ODS_FOLATE, ("folic acid",)),
        FormOption("food_folate", "Food folate (counted 1:1)", 1.0, ODS_FOLATE,
                   note="Methylfolate has no official DFE factor; choosing this counts it 1:1, an approximation."),
    ),
}


def options_for(code: str, unit: str) -> tuple[FormOption, ...]:
    return OPTIONS.get((code, normalize_unit(unit)), ())


def option(code: str, unit: str, key: str) -> FormOption | None:
    return next((o for o in options_for(code, unit) if o.key == key), None)


def auto_resolve(code: str, unit: str, names: list[str]) -> FormOption | None:
    """Pick the conversion when the label's own wording identifies a single factor.

    ``names`` are the row name and its declared forms. Returns None when no form is
    named or the named forms convert differently (e.g. retinol + food carotenoids).
    """
    opts = options_for(code, unit)
    text = [n.lower() for n in names if n]
    matched = {o.key: o for o in opts for n in text if any(p in n for p in o.patterns)}
    factors = {o.factor for o in matched.values()}
    if len(factors) != 1:
        return None
    return next(iter(matched.values()))
