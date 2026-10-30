"""Daily nutrient targets.

Micronutrient reference values are the National Academies Dietary Reference Intakes
for non-pregnant, non-lactating adults (RDA or AI, plus Tolerable Upper Intake Level),
as summarised in the DRI tables published by the NIH Office of Dietary Supplements
(https://ods.od.nih.gov/HealthInformation/nutrientrecommendations.aspx). Sodium and
potassium use the 2019 update. Values were transcribed by hand; verify against the
tables before relying on them, and use per-user overrides for anything else.

Energy is an estimate (Mifflin-St Jeor × activity factor). Macronutrient ranges are
the DRI Acceptable Macronutrient Distribution Ranges; saturated-fat and added-sugar
limits follow the Dietary Guidelines for Americans 2020-2025 (<10% of energy).
"""

from dataclasses import dataclass
from datetime import date

DRI_SOURCE = "National Academies DRI (adults 19+), via NIH ODS DRI tables"

# Age-banded values: list of (max_age_inclusive, value). The last band covers older ages.
Banded = list[tuple[int, float]]


@dataclass(frozen=True)
class Reference:
    kind: str  # RDA | AI
    male: Banded
    female: Banded
    ul: Banded | None = None
    ul_scope: str = "total"  # total | supplemental (UL applies only to supplement/fortificant forms)
    note: str = ""


_ = 200  # sentinel "and older" upper age bound

REFERENCES: dict[str, Reference] = {
    "vitamin_a_ug": Reference("RDA", [(_, 900)], [(_, 700)], [(_, 3000)], "supplemental",
                              "UL applies to preformed vitamin A (retinol) only; beta-carotene does not count."),
    "vitamin_c_mg": Reference("RDA", [(_, 90)], [(_, 75)], [(_, 2000)]),
    "vitamin_d_ug": Reference("RDA", [(70, 15), (_, 20)], [(70, 15), (_, 20)], [(_, 100)]),
    "vitamin_e_mg": Reference("RDA", [(_, 15)], [(_, 15)], [(_, 1000)], "supplemental",
                              "UL applies to supplemental/fortificant alpha-tocopherol."),
    "vitamin_k_ug": Reference("AI", [(_, 120)], [(_, 90)]),
    "thiamin_mg": Reference("RDA", [(_, 1.2)], [(_, 1.1)]),
    "riboflavin_mg": Reference("RDA", [(_, 1.3)], [(_, 1.1)]),
    "niacin_mg": Reference("RDA", [(_, 16)], [(_, 14)], [(_, 35)], "supplemental",
                           "RDA is in niacin equivalents (food data reports preformed niacin). "
                           "UL applies to supplements and fortified foods."),
    "vitamin_b6_mg": Reference("RDA", [(50, 1.3), (_, 1.7)], [(50, 1.3), (_, 1.5)], [(_, 100)]),
    "folate_ug_dfe": Reference("RDA", [(_, 400)], [(_, 400)], [(_, 1000)], "supplemental",
                               "UL is for synthetic folic acid in µg (not DFE); comparing DFE overstates intake ~1.7×."),
    "vitamin_b12_ug": Reference("RDA", [(_, 2.4)], [(_, 2.4)]),
    "pantothenic_mg": Reference("AI", [(_, 5)], [(_, 5)]),
    "biotin_ug": Reference("AI", [(_, 30)], [(_, 30)]),
    "choline_mg": Reference("AI", [(_, 550)], [(_, 425)], [(_, 3500)]),
    "calcium_mg": Reference("RDA", [(70, 1000), (_, 1200)], [(50, 1000), (_, 1200)], [(50, 2500), (_, 2000)]),
    "copper_mg": Reference("RDA", [(_, 0.9)], [(_, 0.9)], [(_, 10)]),
    "iron_mg": Reference("RDA", [(_, 8)], [(50, 18), (_, 8)], [(_, 45)]),
    "magnesium_mg": Reference("RDA", [(30, 400), (_, 420)], [(30, 310), (_, 320)], [(_, 350)], "supplemental",
                              "UL applies to magnesium from supplements and medications only, not food."),
    "manganese_mg": Reference("AI", [(_, 2.3)], [(_, 1.8)], [(_, 11)]),
    "phosphorus_mg": Reference("RDA", [(_, 700)], [(_, 700)], [(70, 4000), (_, 3000)]),
    "selenium_ug": Reference("RDA", [(_, 55)], [(_, 55)], [(_, 400)]),
    "zinc_mg": Reference("RDA", [(_, 11)], [(_, 8)], [(_, 40)]),
    "iodine_ug": Reference("RDA", [(_, 150)], [(_, 150)], [(_, 1100)]),
    "potassium_mg": Reference("AI", [(_, 3400)], [(_, 2600)]),
    "fiber_g": Reference("AI", [(50, 38), (_, 30)], [(50, 25), (_, 21)]),
}

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
GOAL_FACTORS = {"lose": 0.85, "maintain": 1.0, "gain": 1.10}


def _band(values: Banded, age: int) -> float:
    for max_age, value in values:
        if age <= max_age:
            return value
    return values[-1][1]


def age_on(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def estimate_energy_kcal(sex: str, age: int, weight_kg: float, height_cm: float, activity: str, goal: str) -> float:
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)
    return bmr * ACTIVITY_FACTORS.get(activity, 1.55) * GOAL_FACTORS.get(goal, 1.0)


def compute_targets(profile, today: date) -> dict:
    """Return {"targets": {code: {...}}, "warnings": [...]} for a Profile (or None)."""
    targets: dict[str, dict] = {}
    warnings: list[str] = []

    sex = getattr(profile, "sex", None)
    age = age_on(profile.birth_date, today) if profile and profile.birth_date else None
    weight = getattr(profile, "weight_kg", None)
    height = getattr(profile, "height_cm", None)
    life_stage = getattr(profile, "life_stage", "none") or "none"

    if sex not in ("male", "female") or age is None:
        warnings.append("Set sex and birth date in your profile to get reference intakes.")
    elif age < 19:
        warnings.append("Reference intakes for people under 19 are not built in; set targets manually.")
    else:
        dri_ok = life_stage == "none"
        if not dri_ok:
            warnings.append(
                f"Reference intakes for {life_stage} people differ from the adult values and are not built in. "
                "Only upper limits are shown; set targets with your clinician's guidance."
            )
        for code, ref in REFERENCES.items():
            entry = {"min": None, "target": None, "max": None, "kind": ref.kind, "source": DRI_SOURCE,
                     "ul_scope": None, "note": ref.note}
            if dri_ok:
                entry["target"] = _band(ref.male if sex == "male" else ref.female, age)
            if ref.ul:
                entry["max"] = _band(ref.ul, age)
                entry["ul_scope"] = ref.ul_scope
            if entry["target"] is not None or entry["max"] is not None:
                targets[code] = entry
        targets["sodium_mg"] = {
            "min": None, "target": 1500 if dri_ok else None, "max": 2300, "kind": "AI/CDRR", "source": DRI_SOURCE,
            "ul_scope": "total", "note": "Max is the Chronic Disease Risk Reduction intake, not a UL.",
        }

        if weight and height:
            kcal = estimate_energy_kcal(sex, age, weight, height, profile.activity_level, profile.goal)
            targets["energy_kcal"] = {
                "min": None, "target": round(kcal), "max": None, "kind": "estimate",
                "source": "Mifflin-St Jeor × activity factor", "ul_scope": None,
                "note": "An estimate; adjust using your weight trend.",
            }
            amdr = "DRI Acceptable Macronutrient Distribution Range"
            targets["protein_g"] = {
                "min": round(0.8 * weight, 1) if dri_ok else None, "target": None, "max": round(kcal * 0.35 / 4),
                "kind": "RDA/AMDR", "source": amdr, "ul_scope": None,
                "note": "Min is the RDA (0.8 g/kg); max is 35% of energy.",
            }
            targets["fat_g"] = {"min": round(kcal * 0.20 / 9), "target": None, "max": round(kcal * 0.35 / 9),
                                "kind": "AMDR", "source": amdr, "ul_scope": None, "note": "20–35% of energy."}
            targets["carbs_g"] = {"min": round(kcal * 0.45 / 4), "target": None, "max": round(kcal * 0.65 / 4),
                                  "kind": "AMDR", "source": amdr, "ul_scope": None, "note": "45–65% of energy."}
            dga = "Dietary Guidelines for Americans 2020–2025"
            targets["sat_fat_g"] = {"min": None, "target": None, "max": round(kcal * 0.10 / 9), "kind": "limit",
                                    "source": dga, "ul_scope": None, "note": "<10% of energy."}
            targets["added_sugars_g"] = {"min": None, "target": None, "max": round(kcal * 0.10 / 4), "kind": "limit",
                                         "source": dga, "ul_scope": None, "note": "<10% of energy."}
        else:
            warnings.append("Add height and weight to estimate energy and macronutrient targets.")

    for code, override in ((getattr(profile, "target_overrides", None) or {}).items()):
        base = targets.get(code, {"ul_scope": None, "note": ""})
        targets[code] = {**base, **{k: override.get(k) for k in ("min", "target", "max")},
                         "kind": "override", "source": "Your override"}

    return {"targets": targets, "warnings": warnings}
