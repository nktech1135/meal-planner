"""Parsers for the UK CoFID 2021 and German BLS 4.0 food composition databases (excerpt fixtures)."""

import pytest

from app.services.datasets import BY_KEY
from app.sources.intl import bls, cofid
from tests.conftest import FIXTURES

INTL = FIXTURES / "intl"


@pytest.fixture(scope="module")
def cofid_foods():
    return {f.source_id: f for f in cofid.parse({"data": INTL / "cofid" / "cofid2021_excerpt.xlsx"})}


@pytest.fixture(scope="module")
def bls_foods():
    return {f.source_id: f for f in bls.parse({"zip": INTL / "bls" / "bls40_excerpt.zip"})}


def value(food, code):
    return food.nutrients[code][0]


def note(food, code):
    return food.nutrients[code][1] or ""


# --- CoFID 2021 ---------------------------------------------------------------------------


def test_cofid_food_metadata(cofid_foods):
    apple = cofid_foods["14-319"]
    assert apple.source == "cofid" and apple.name == "Apples, eating, raw, flesh and skin"
    assert apple.data_type == "CoFID 2021" and apple.trust_level == "analytical" and apple.basis == "100g"
    assert apple.category == "Fruit: Fruit, general"
    assert apple.state == "raw"
    assert apple.citation == BY_KEY["intl_cofid"].attribution.rstrip(".") + ". Food 14-319."
    assert "Open Government Licence v3.0" in apple.citation
    assert cofid_foods["13-490"].category == "Vegetables: Main crop potatoes"
    assert cofid_foods["12-596"].category == "Milk and milk products: Whole milk"


def test_cofid_duplicate_code_keeps_both_foods(cofid_foods):
    # The published file uses 13-669 for two different foods.
    assert cofid_foods["13-669"].name.startswith("Aubergine")
    assert cofid_foods["13-669#2"].name == "Watercress, raw"
    assert value(cofid_foods["13-669#2"], "vitamin_k_ug") == 315  # its own row, not the aubergine's
    assert cofid_foods["13-669#2"].citation.endswith("Food 13-669.")
    assert len(cofid_foods) == 10


def test_cofid_direct_values_and_units(cofid_foods):
    milk = cofid_foods["12-596"]
    assert value(milk, "energy_kcal") == 63
    assert value(milk, "protein_g") == 3.4 and value(milk, "fat_g") == 3.6
    assert value(milk, "sodium_mg") == 42 and value(milk, "calcium_mg") == 120
    assert value(milk, "iodine_ug") == 31 and value(milk, "vitamin_b12_ug") == 0.9
    assert value(milk, "sat_fat_g") == 2.29 and value(milk, "trans_fat_g") == 0.13  # per 100 g food
    assert value(milk, "cholesterol_mg") == 12
    assert note(milk, "energy_kcal") == "CoFID 2021"
    assert value(cofid_foods["13-490"], "potassium_mg") == 365


def test_cofid_markers(cofid_foods):
    potato = cofid_foods["13-490"]
    assert value(potato, "riboflavin_mg") == 0 and note(potato, "riboflavin_mg").endswith("trace")  # "Tr"
    assert value(potato, "vitamin_c_mg") == 9 and note(potato, "vitamin_c_mg").endswith("estimate")  # "(9)"
    cornflakes = cofid_foods["11-742"]
    assert "pantothenic_mg" not in cornflakes.nutrients  # "N": present but unknown -> missing, not zero
    assert "iodine_ug" not in cofid_foods["17-506"].nutrients  # "N"
    assert "vitamin_k_ug" not in cofid_foods["13-490"].nutrients  # blank: not measured


def test_cofid_carbohydrate_is_available_as_weight_plus_aoac_fibre(cofid_foods):
    potato = cofid_foods["13-490"]  # CHO 17.5 (starch 16.7, glucose 0.3, fructose 0.3), AOAC fibre 1.6
    assert value(potato, "fiber_g") == 1.6 and "AOAC" in note(potato, "fiber_g")
    assert value(potato, "carbs_g") == pytest.approx(16.7 / 1.10 + 0.6 + 0.2 / 1.05 + 1.6)
    assert "available carbohydrate" in note(potato, "carbs_g")
    milk = cofid_foods["12-596"]  # all lactose
    assert value(milk, "carbs_g") == pytest.approx(4.6 / 1.05)
    assert value(milk, "sugars_g") == pytest.approx(4.6 / 1.05)
    apple = cofid_foods["14-319"]  # glucose 2.1, fructose 6.7, sucrose 2.8
    assert value(apple, "sugars_g") == pytest.approx(2.1 + 6.7 + 2.8 / 1.05)


def test_cofid_without_aoac_fibre_has_no_total_carbohydrate(cofid_foods):
    apricots = cofid_foods["14-031"]  # only NSP (Englyst) fibre is given
    assert "fiber_g" not in apricots.nutrients and "carbs_g" not in apricots.nutrients
    assert value(apricots, "sugars_g") == 43.4 and "monosaccharide" in note(apricots, "sugars_g")


def test_cofid_vitamin_a_is_rae_and_re_te_are_not_mapped(cofid_foods):
    milk = cofid_foods["12-596"]  # retinol 36, carotene (beta-carotene equivalents) 14, RE 38
    assert value(milk, "vitamin_a_ug") == pytest.approx(36 + 14 / 12)
    assert "RAE" in note(milk, "vitamin_a_ug")
    # Vitamin E (alpha-TE) 0.06 is not mapped and milk has no alpha-tocopherol fraction.
    assert "vitamin_e_mg" not in milk.nutrients
    assert value(cofid_foods["14-319"], "vitamin_e_mg") == 0.09  # from alpha-tocopherol (fractions)
    for food in cofid_foods.values():
        assert not {"retinol_ug", "beta_carotene_ug", "energy_kj", "available_carbs_g"} & food.nutrients.keys()


def test_cofid_vitamin_d_folate_and_niacin(cofid_foods):
    bacon = cofid_foods["19-500"]  # VITD includes 5 x 25-OH D3; cholecalciferol 0.30
    assert value(bacon, "vitamin_d_ug") == 0.3 and "cholecalciferol" in note(bacon, "vitamin_d_ug")
    assert value(cofid_foods["11-742"], "vitamin_d_ug") == 4.7
    potato = cofid_foods["13-490"]
    assert value(potato, "folate_ug_dfe") == 18 and "DFE" in note(potato, "folate_ug_dfe")
    assert "folate_ug_dfe" not in cofid_foods["11-742"].nutrients  # fortified: total folate understates DFE
    assert value(cofid_foods["11-742"], "niacin_mg") == 15.8
    assert "preformed" in note(cofid_foods["11-742"], "niacin_mg")


def test_cofid_alcoholic_drinks_are_converted_from_per_100_ml(cofid_foods):
    cider = cofid_foods["17-222"]  # specific gravity 1.01
    assert value(cider, "energy_kcal") == pytest.approx(36 / 1.01)
    assert value(cider, "alcohol_g") == pytest.approx(3.8 / 1.01)
    assert "per 100 ml / specific gravity 1.01" in note(cider, "alcohol_g")
    beer = cofid_foods["17-506"]  # no specific gravity: kept as published
    assert value(beer, "energy_kcal") == 30 and "per 100 ml" in note(beer, "energy_kcal")


# --- BLS 4.0 --------------------------------------------------------------------------------


def test_bls_food_metadata(bls_foods):
    assert set(bls_foods) == {"F110100", "K110132", "M111300", "P253000", "C515100", "Y361623", "B121000"}
    apple = bls_foods["F110100"]
    assert apple.source == "bls" and apple.name == "Apple raw" and apple.data_type == "BLS 4.0"
    assert apple.category == "Fruit and fruit products" and apple.state == "raw"
    assert apple.citation == BY_KEY["intl_bls"].attribution.rstrip(".") + ". Food F110100."
    assert "CC BY 4.0" in apple.citation
    assert bls_foods["M111300"].category == "Milk and dairy products"
    assert bls_foods["Y361623"].category == "Dishes: meals and desserts"
    assert bls_foods["B121000"].category == "Bread and rolls"


def test_bls_values_units_and_data_origin(bls_foods):
    milk = bls_foods["M111300"]
    assert value(milk, "energy_kcal") == 62 and value(milk, "protein_g") == 3.55 and value(milk, "fat_g") == 3.49
    assert value(milk, "sodium_mg") == 34.9
    assert value(milk, "vitamin_b6_mg") == pytest.approx(0.039)  # published as 39 µg
    assert value(milk, "copper_mg") == pytest.approx(0.0064)  # published as 6.4 µg
    assert note(milk, "sodium_mg") == "BLS 4.0; origin: analysis"
    assert note(milk, "vitamin_b6_mg") == "BLS 4.0; origin: other nutrient database"
    assert "N × 6.25" in note(milk, "protein_g")
    dish = bls_foods["Y361623"]
    assert note(dish, "sodium_mg") == "BLS 4.0; origin: recipe calculation"
    assert note(bls_foods["F110100"], "cholesterol_mg") == "BLS 4.0; origin: logical zero"
    assert note(bls_foods["C515100"], "niacin_mg") == "BLS 4.0; origin: product label"


def test_bls_markers(bls_foods):
    wine = bls_foods["P253000"]
    assert value(wine, "protein_g") == 0 and note(wine, "protein_g").endswith("trace")  # "TR"
    assert value(wine, "vitamin_b6_mg") == 0 and "below limit (<LOD)" in note(wine, "vitamin_b6_mg")
    assert value(wine, "vitamin_c_mg") == 0 and "below limit (<LOQ)" in note(wine, "vitamin_c_mg")
    bread = bls_foods["B121000"]
    assert "iodine_ug" not in bread.nutrients  # "-": missing, not zero
    assert value(bread, "cholesterol_mg") == 0 and note(bread, "cholesterol_mg") == "BLS 4.0; trace"


def test_bls_carbohydrate_is_available_plus_fibre(bls_foods):
    apple = bls_foods["F110100"]  # CHO 11.7 (available), FIBT 2.275
    assert value(apple, "fiber_g") == 2.275
    assert value(apple, "carbs_g") == pytest.approx(11.7 + 2.275)
    assert "available carbohydrate + fibre" in note(apple, "carbs_g")
    assert value(apple, "sugars_g") == 10.487


def test_bls_vitamin_definitions(bls_foods):
    apple = bls_foods["F110100"]  # VITA (RE) 4, VITAA (RAE) 2
    assert value(apple, "vitamin_a_ug") == 2 and "RAE" in note(apple, "vitamin_a_ug")
    assert value(apple, "vitamin_e_mg") == 0.172  # alpha-tocopherol
    milk = bls_foods["M111300"]
    assert value(milk, "vitamin_a_ug") == 24
    cornflakes = bls_foods["C515100"]  # FOL = food folate + 1.7 x 181 µg folic acid
    assert value(cornflakes, "folate_ug_dfe") == 311 and "DFE" in note(cornflakes, "folate_ug_dfe")
    for food in bls_foods.values():
        assert "trans_fat_g" not in food.nutrients and "selenium_ug" not in food.nutrients
        assert not {"energy_kj", "available_carbs_g"} & food.nutrients.keys()


def test_derivations_fit_the_database_column(cofid_foods, bls_foods):
    for food in [*cofid_foods.values(), *bls_foods.values()]:
        for _, derivation in food.nutrients.values():
            assert derivation and len(derivation) <= 120
        assert food.category and len(food.category) <= 120
