from datetime import date
from types import SimpleNamespace

import pytest

from app.models import CookingYield, Food, FoodNutrient, FoodPortion, Recipe, RecipeIngredient
from app.services.nutrition import NutritionError, derive_yield, food_nutrition, recipe_nutrition, recipe_portion
from app.services.targets import compute_targets, estimate_energy_kcal


def make_food(fid=1, basis="100g", trust="analytical", state="raw", **nutrients) -> Food:
    food = Food(id=fid, name=f"food{fid}", basis=basis, trust_level=trust, state=state, kind="food",
                other_components=[])
    food.nutrients = [FoodNutrient(nutrient_code=k, amount=v) for k, v in nutrients.items()]
    food.portions = []
    return food


def test_grams_on_100g_basis():
    food = make_food(energy_kcal=200, protein_g=20)
    result = food_nutrition(food, 150, "g")
    assert result.nutrients == {"energy_kcal": 300, "protein_g": 30}
    assert result.grams == 150
    assert result.trust_level == "analytical"


def test_portion_unit():
    food = make_food(energy_kcal=100)
    food.portions = [FoodPortion(id=7, label="1 cup", gram_weight=240)]
    result = food_nutrition(food, 0.5, "portion:7")
    assert result.grams == 120
    assert result.nutrients["energy_kcal"] == 120


def test_supplement_units_and_components():
    supp = make_food(basis="serving", trust="label", state=None, vitamin_d_ug=25, calcium_mg=1200)
    supp.kind, supp.serving_quantity, supp.serving_unit = "supplement", 2, "Softgel(s)"
    supp.other_components = [{"name": "Ashwagandha", "amount": 300, "unit": "mg"}]
    one_softgel = food_nutrition(supp, 1, "unit")
    assert one_softgel.nutrients == {"vitamin_d_ug": 12.5, "calcium_mg": 600}
    assert one_softgel.other_components[0]["amount"] == 150
    with pytest.raises(NutritionError):
        food_nutrition(supp, 10, "g")  # no serving weight known


def test_cooked_weight_converts_back_to_raw_with_retention():
    chicken = make_food(energy_kcal=120, protein_g=22.5, vitamin_b6_mg=0.6)
    y = CookingYield(id=3, raw_food_id=1, method="roasted", yield_factor=0.75, retention={"vitamin_b6_mg": 0.5},
                     basis="measured", trust_level="user")
    result = food_nutrition(chicken, 150, "g", "cooked", y)
    # 150 g cooked / 0.75 = 200 g raw
    assert result.grams == pytest.approx(200)
    assert result.nutrients["protein_g"] == pytest.approx(45)
    assert result.nutrients["vitamin_b6_mg"] == pytest.approx(0.6)  # 1.2 × 0.5 retention
    assert result.trust_level == "user"  # weakest of analytical food and user-measured yield
    assert any("200.0 g raw" in n for n in result.notes)


def test_cooked_weight_requires_matching_yield():
    chicken = make_food()
    with pytest.raises(NutritionError):
        food_nutrition(chicken, 100, "g", "cooked", None)
    other = CookingYield(id=4, raw_food_id=99, method="boiled", yield_factor=2.5, retention={}, basis="measured",
                         trust_level="user")
    with pytest.raises(NutritionError):
        food_nutrition(chicken, 100, "g", "cooked", other)


def _recipe():
    rice = make_food(1, energy_kcal=360, protein_g=7)
    oil = make_food(2, trust="user", state=None, energy_kcal=884, fat_g=100)
    recipe = Recipe(id=1, name="Rice", servings=4, cooked_weight_g=750)
    recipe.ingredients = [
        RecipeIngredient(id=1, food_id=1, food=rice, grams=300, weighed_state="as_is"),
        RecipeIngredient(id=2, food_id=2, food=oil, grams=10, weighed_state="as_is"),
    ]
    return recipe


def test_recipe_totals_per_serving_and_per_100g_cooked():
    info = recipe_nutrition(_recipe(), {})
    assert info["total"]["energy_kcal"] == pytest.approx(1080 + 88.4)
    assert info["per_serving"]["energy_kcal"] == pytest.approx(1168.4 / 4)
    assert info["per_100g_cooked"]["energy_kcal"] == pytest.approx(1168.4 / 7.5)
    assert info["ingredient_mass_g"] == 310
    assert info["trust_level"] == "user"


def test_recipe_portion_by_cooked_grams():
    portion = recipe_portion(_recipe(), {}, 150, "g")
    assert portion.nutrients["energy_kcal"] == pytest.approx(1168.4 * 150 / 750)


def test_derive_yield_from_protein():
    raw = make_food(1, protein_g=22.5, water_g=75)
    cooked = make_food(2, state="cooked", protein_g=30, water_g=65)
    out = derive_yield(raw, cooked)
    assert out["yield_factor"] == pytest.approx(0.75)
    assert out["dry_matter_check"] == pytest.approx(25 / 35, abs=1e-4)


def profile(**kw):
    base = dict(sex="male", birth_date=date(1990, 6, 1), height_cm=180, weight_kg=80, activity_level="moderate",
                goal="maintain", life_stage="none", target_overrides={})
    return SimpleNamespace(**{**base, **kw})


def test_energy_estimate_mifflin_st_jeor():
    assert estimate_energy_kcal("male", 30, 80, 180, "moderate", "maintain") == pytest.approx(1780 * 1.55)
    assert estimate_energy_kcal("female", 30, 60, 165, "sedentary", "maintain") == pytest.approx(
        (600 + 1031.25 - 150 - 161) * 1.2)


def test_reference_intakes_by_sex_and_age():
    today = date(2026, 10, 30)
    male36 = compute_targets(profile(), today)["targets"]
    assert male36["magnesium_mg"]["target"] == 420
    assert male36["magnesium_mg"]["ul_scope"] == "supplemental"
    assert male36["iron_mg"]["target"] == 8
    female40 = compute_targets(profile(sex="female", birth_date=date(1986, 1, 1)), today)["targets"]
    assert female40["iron_mg"]["target"] == 18
    female60 = compute_targets(profile(sex="female", birth_date=date(1966, 1, 1)), today)["targets"]
    assert female60["iron_mg"]["target"] == 8
    assert female60["calcium_mg"]["target"] == 1200
    assert female60["calcium_mg"]["max"] == 2000


def test_pregnancy_shows_only_upper_limits_and_warns():
    result = compute_targets(profile(sex="female", life_stage="pregnant"), date(2026, 10, 30))
    assert result["targets"]["iron_mg"]["target"] is None
    assert result["targets"]["iron_mg"]["max"] == 45
    assert any("pregnant" in w for w in result["warnings"])


def test_overrides_win():
    result = compute_targets(profile(target_overrides={"protein_g": {"min": 140, "target": 160, "max": None}}),
                             date(2026, 10, 30))
    assert result["targets"]["protein_g"]["target"] == 160
    assert result["targets"]["protein_g"]["kind"] == "override"
