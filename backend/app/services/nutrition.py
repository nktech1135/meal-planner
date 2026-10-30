"""Nutrient arithmetic: portions, servings, raw↔cooked conversion and recipes."""

from dataclasses import dataclass, field

from app.models import CookingYield, Food, Recipe
from app.nutrients import BY_CODE, Trust, weakest


class NutritionError(ValueError):
    pass


@dataclass
class Nutrition:
    nutrients: dict[str, float]
    grams: float | None  # mass of the food as described (raw mass for raw foods)
    trust_level: str
    other_components: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def scale(values: dict[str, float], factor: float) -> dict[str, float]:
    return {k: v * factor for k, v in values.items()}


def add_into(total: dict[str, float], values: dict[str, float]) -> None:
    for k, v in values.items():
        total[k] = total.get(k, 0.0) + v


def rounded(values: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in values.items()}


def _basis_factor(food: Food, quantity: float, unit: str) -> tuple[float, float | None]:
    """Return (multiplier on the food's nutrient basis, resolved grams or None)."""
    if quantity < 0:
        raise NutritionError("Quantity must be positive")
    portion_grams = None
    if unit.startswith("portion:"):
        pid = int(unit.split(":", 1)[1])
        portion = next((p for p in food.portions if p.id == pid), None)
        if portion is None:
            raise NutritionError("Unknown portion for this food")
        portion_grams = portion.gram_weight * quantity

    if food.basis == "100g":
        if unit == "g":
            return quantity / 100, quantity
        if portion_grams is not None:
            return portion_grams / 100, portion_grams
        if unit == "serving":
            if not food.serving_size_g:
                raise NutritionError("This food has no serving size in grams; log it in grams")
            grams = food.serving_size_g * quantity
            return grams / 100, grams
    else:  # per-serving basis (supplements, some labels)
        if unit == "serving":
            return quantity, (food.serving_size_g * quantity if food.serving_size_g else None)
        if unit == "unit":  # individual capsules/tablets/scoops
            per_serving = food.serving_quantity or 1
            return quantity / per_serving, None
        if unit == "g" or portion_grams is not None:
            grams = quantity if unit == "g" else portion_grams
            if not food.serving_size_g:
                raise NutritionError("This item has no serving weight; log it in servings")
            return grams / food.serving_size_g, grams
    raise NutritionError(f"Unsupported unit '{unit}' for this food")


def food_nutrition(
    food: Food,
    quantity: float,
    unit: str,
    weighed_state: str = "as_is",
    cooking_yield: CookingYield | None = None,
    form_factors: dict[str, tuple[str, float, str]] | None = None,
) -> Nutrition:
    """``form_factors`` maps an unconverted component's name to (nutrient code, factor, form label),
    from the user's own choice of form; such amounts count toward that nutrient as user data."""
    notes: list[str] = []
    trust = [food.trust_level]

    if weighed_state == "cooked" and food.state != "cooked":
        # The user weighed the cooked result of a raw food: convert back to raw mass.
        if cooking_yield is None:
            raise NutritionError("Choose a cooking yield to convert cooked weight to raw")
        if cooking_yield.raw_food_id != food.id:
            raise NutritionError("That cooking yield is for a different food")
        if food.basis != "100g":
            raise NutritionError("Cooked-weight conversion needs a per-100 g food")
        if unit == "g":
            cooked_grams = quantity
        else:
            _, cooked_grams = _basis_factor(food, quantity, unit)
            if cooked_grams is None:
                raise NutritionError("Log cooked weight in grams")
        raw_grams = cooked_grams / cooking_yield.yield_factor
        trust.append(cooking_yield.trust_level)
        notes.append(
            f"{cooked_grams:g} g {cooking_yield.method} ≈ {raw_grams:.1f} g raw "
            f"(yield {cooking_yield.yield_factor:.3f}, {cooking_yield.basis})"
        )
        cooked_food = cooking_yield.cooked_food
        if cooked_food is not None and cooked_food.basis == "100g" and cooked_food.nutrients:
            # A separately analysed cooked entry already reflects cooking losses: use it directly.
            nutrients = scale(cooked_food.nutrient_map(), cooked_grams / 100)
            trust.append(cooked_food.trust_level)
            notes.append(f"Nutrients from the cooked entry “{cooked_food.name}”.")
        else:
            base = scale(food.nutrient_map(), raw_grams / 100)
            retention = cooking_yield.retention or {}
            nutrients = {k: v * float(retention.get(k, 1.0)) for k, v in base.items()}
            notes.append(
                "Cooking-loss retention factors applied." if retention
                else "No retention factors on this yield: nutrients assumed fully retained (vitamins may be overstated)."
            )
        factor, grams = raw_grams / 100, raw_grams
    else:
        factor, grams = _basis_factor(food, quantity, unit)
        nutrients = scale(food.nutrient_map(), factor)

    others = []
    for c in food.other_components or []:
        if c.get("amount") is None:
            continue
        choice = (form_factors or {}).get(c["name"])
        if choice and c.get("nutrient_code") == choice[0]:
            code, conv, form = choice
            nutrients[code] = nutrients.get(code, 0.0) + c["amount"] * conv * factor
            trust.append(Trust.USER)
            notes.append(f"{c['name']}: {c['amount']:g} {c.get('unit') or ''} counted as {form} (×{conv:g}, your choice)")
        else:
            others.append({**c, "amount": c["amount"] * factor})
    return Nutrition(rounded(nutrients), grams, weakest(trust), others, notes)


def recipe_nutrition(recipe: Recipe, yields: dict[int, CookingYield]) -> dict:
    total: dict[str, float] = {}
    trust = []
    notes: list[str] = []
    others: list[dict] = []
    ingredient_rows = []
    raw_total = 0.0
    for ing in recipe.ingredients:
        result = food_nutrition(
            ing.food, ing.grams, "g", ing.weighed_state, yields.get(ing.yield_id) if ing.yield_id else None
        )
        add_into(total, result.nutrients)
        trust.append(result.trust_level)
        others.extend(result.other_components)
        raw_total += result.grams or 0
        notes.extend(f"{ing.food.name}: {n}" for n in result.notes)
        ingredient_rows.append({"id": ing.id, "food_id": ing.food_id, "grams": result.grams,
                                "nutrients": result.nutrients, "trust_level": result.trust_level})

    servings = recipe.servings or 1
    per_100g = scale(total, 100 / recipe.cooked_weight_g) if recipe.cooked_weight_g else None
    if not recipe.cooked_weight_g:
        notes.append("Weigh the finished dish and set its cooked weight to log it by grams.")
    return {
        "total": rounded(total),
        "per_serving": rounded(scale(total, 1 / servings)),
        "per_100g_cooked": rounded(per_100g) if per_100g else None,
        "ingredient_mass_g": round(raw_total, 2),
        "trust_level": weakest(trust) or "user",
        "other_components": others,
        "ingredients": ingredient_rows,
        "notes": notes,
    }


def recipe_portion(recipe: Recipe, yields: dict[int, CookingYield], quantity: float, unit: str) -> Nutrition:
    info = recipe_nutrition(recipe, yields)
    if unit == "serving":
        factor = quantity / (recipe.servings or 1)
        grams = recipe.cooked_weight_g * factor if recipe.cooked_weight_g else None
    elif unit == "g":
        if not recipe.cooked_weight_g:
            raise NutritionError("Set the recipe's cooked weight to log it in grams")
        factor, grams = quantity / recipe.cooked_weight_g, quantity
    else:
        raise NutritionError("Log recipes in servings or grams")
    others = [{**c, "amount": c["amount"] * factor} for c in info["other_components"]]
    return Nutrition(rounded(scale(info["total"], factor)), grams, info["trust_level"], others, info["notes"])


def derive_yield(raw: Food, cooked: Food) -> dict:
    """Estimate a cooking yield from paired raw and cooked nutrient profiles.

    Protein barely leaves food during cooking, so the ratio of protein per 100 g
    (raw / cooked) approximates cooked mass / raw mass. The dry-matter ratio is
    reported as a cross-check; it underestimates yield when fat renders out.
    """
    if raw.basis != "100g" or cooked.basis != "100g":
        raise NutritionError("Both foods must be per-100 g")
    r, c = raw.nutrient_map(), cooked.nutrient_map()
    if not r.get("protein_g") or not c.get("protein_g"):
        raise NutritionError("Both foods need protein values to derive a yield")
    estimate = r["protein_g"] / c["protein_g"]
    check = None
    if r.get("water_g") is not None and c.get("water_g") is not None and c["water_g"] < 100:
        check = (100 - r["water_g"]) / (100 - c["water_g"])
    return {
        "yield_factor": round(estimate, 4),
        "dry_matter_check": round(check, 4) if check else None,
        "trust_level": weakest([raw.trust_level, cooked.trust_level]),
        "method_note": "Derived from protein conservation between paired raw and cooked entries; an estimate.",
    }


def summarize(totals: dict[str, float]) -> list[dict]:
    """Attach names and units, in catalog order."""
    order = list(BY_CODE)
    rows = []
    for code in sorted(totals, key=lambda c: order.index(c) if c in BY_CODE else len(order)):
        n = BY_CODE.get(code)
        rows.append({"code": code, "name": n.name if n else code, "unit": n.unit if n else "", "amount": totals[code]})
    return rows
