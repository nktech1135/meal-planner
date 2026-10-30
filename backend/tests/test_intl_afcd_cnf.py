"""Parsers for the Australian Food Composition Database (AFCD) and the Canadian Nutrient File (CNF),
run on small excerpts of the published files (see tests/fixtures/intl/*/README.md)."""

from pathlib import Path

import pytest

from app.nutrients import BY_CODE
from app.services.datasets import BY_KEY
from app.sources.intl import afcd, cnf

FIXTURES = Path(__file__).parent / "fixtures" / "intl"


@pytest.fixture(scope="module")
def afcd_foods():
    files = {"profiles": FIXTURES / "afcd" / "profiles.xlsx", "details": FIXTURES / "afcd" / "details.xlsx"}
    return {f.source_id: f for f in afcd.parse(files)}


@pytest.fixture(scope="module")
def cnf_foods():
    return {f.source_id: f for f in cnf.parse({"zip": FIXTURES / "cnf" / "cnf_excerpt.zip"})}


def amount(food, code):
    return food.nutrients[code][0]


def note(food, code):
    return food.nutrients[code][1]


# --- AFCD -----------------------------------------------------------------------------------------


def test_afcd_food_metadata(afcd_foods):
    assert set(afcd_foods) == {"F000110", "F007661", "F005634", "F004380", "F005602"}
    apple = afcd_foods["F000110"]
    assert apple.source == "afcd" and apple.name == "Apple, red skin, unpeeled, raw"
    assert apple.data_type == "AFCD Release 3"
    assert apple.category == "Fruit products and dishes"  # classification 16101 -> AUSNUT major group 16
    assert apple.state == "raw" and apple.basis == "100g" and apple.trust_level == "analytical"
    assert apple.citation == BY_KEY["intl_afcd"].attribution.rstrip(".") + ". Food F000110."
    assert "CC BY 4.0" in apple.citation
    assert afcd_foods["F007661"].category == "Cereals and cereal products"


def test_afcd_energy_from_kj_and_carbs_from_available_plus_fibre(afcd_foods):
    apple = afcd_foods["F000110"]
    assert amount(apple, "energy_kcal") == pytest.approx(242 / 4.184)  # published only as 242 kJ
    assert note(apple, "energy_kcal") == "AFCD: Analysed; converted from kJ"
    assert amount(apple, "carbs_g") == pytest.approx(13.1 + 2.5)  # available carbohydrate + total dietary fibre
    assert "available carbohydrate + fibre" in note(apple, "carbs_g")
    assert amount(apple, "fiber_g") == 2.5
    assert amount(apple, "sugars_g") == 12.4
    assert amount(apple, "vitamin_c_mg") == 7
    assert note(apple, "vitamin_c_mg") == "AFCD: Analysed"


def test_afcd_units_and_derived_vitamins(afcd_foods):
    milk = afcd_foods["F005634"]
    assert amount(milk, "protein_g") == 3.3 and amount(milk, "fat_g") == 3.4
    assert amount(milk, "calcium_mg") == 106 and amount(milk, "sodium_mg") == 35
    assert amount(milk, "selenium_ug") == 1.2  # published in ug
    assert amount(milk, "trans_fat_g") == pytest.approx(0.09928)  # published as 99.28 mg
    assert "imputed where not analysed" in note(milk, "trans_fat_g")
    # RAE = retinol 41 + beta-carotene equivalents 18 / 12; the retinol-equivalents column (44) is ignored.
    assert amount(milk, "vitamin_a_ug") == pytest.approx(41 + 18 / 12)
    assert "beta-carotene equivalents/12" in note(milk, "vitamin_a_ug")
    assert amount(milk, "vitamin_e_mg") == 0.1  # alpha-tocopherol, not AFCD "Vitamin E" (0.09)
    assert amount(milk, "vitamin_d_ug") == 0 and note(milk, "vitamin_d_ug").endswith("D3 + D2")
    assert amount(milk, "folate_ug_dfe") == 5
    assert milk.portions == [("100 mL", 103.0)]  # specific gravity 1.03
    assert afcd_foods["F000110"].portions == []


def test_afcd_derivation_and_unmapped(afcd_foods):
    assert note(afcd_foods["F005602"], "protein_g") == "AFCD: Recipe"
    honey = afcd_foods["F004380"]
    assert amount(honey, "sugars_g") == 72.3
    assert "added_sugars_g" not in honey.nutrients  # AUSNUT added sugars exclude honey; not the U.S. definition
    assert "biotin_ug" not in afcd_foods["F007661"].nutrients  # empty cell = unknown, not zero
    assert amount(afcd_foods["F000110"], "selenium_ug") == 0  # a published 0 stays 0
    for food in afcd_foods.values():
        assert {"vitamin_k_ug", "choline_mg", "added_sugars_g"}.isdisjoint(food.nutrients)


def test_afcd_rejects_unknown_layout(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = afcd.SHEET
    ws.append(["title"])
    ws.append([])
    ws.append(["Public Food Key", "Classification", "Derivation", "Food Name", "Protein (g)"])
    ws.append(["F1", 16101, "Analysed", "Thing", 1])
    wb.save(tmp_path / "p.xlsx")
    with pytest.raises(ValueError, match="columns not found"):
        list(afcd.parse({"profiles": tmp_path / "p.xlsx"}))


# --- CNF ------------------------------------------------------------------------------------------


def test_cnf_skips_foods_copied_unchanged_from_usda(cnf_foods):
    assert "5" not in cnf_foods  # Food_Source_Code 0: "Food based on data from USDA: No changes"
    assert set(cnf_foods) == {"1696", "113", "4066", "3241", "4516", "1260"}


def test_cnf_food_metadata_and_portions(cnf_foods):
    apple = cnf_foods["1696"]
    assert apple.source == "cnf" and apple.name == "Apple, raw, with skin" and apple.data_type == "CNF 2026"
    assert apple.category == "Fruits and fruit juices" and apple.state == "raw"
    assert apple.citation == BY_KEY["intl_cnf"].attribution.rstrip(".") + ". Food 1696."
    assert "Open Government Licence – Canada" in apple.citation
    assert ("1 medium fruit (7cm dia)", 182.0) in apple.portions
    assert ("250 ml chopped", 132.079) in apple.portions
    assert all(label != "total refuse" for label, _ in apple.portions)  # refuse/yield rows aren't portions


def test_cnf_values_units_and_derivations(cnf_foods):
    milk = cnf_foods["113"]
    assert amount(milk, "energy_kcal") == 59  # code 208 as published, not 247 kJ converted
    assert note(milk, "energy_kcal") == "CNF; Calculated from analytical Canadian data"
    assert amount(milk, "fat_g") == 3.094 and note(milk, "fat_g") == "CNF; Nutrient analyzed in a Canadian government lab"
    assert amount(milk, "carbs_g") == 4.46 and amount(milk, "sugars_g") == 3.89
    assert amount(milk, "selenium_ug") == 3.88
    assert amount(milk, "vitamin_a_ug") == 63.48  # 320 RAE
    assert amount(milk, "vitamin_d_ug") == pytest.approx(1.939337522)  # 328 in ug, not the IU row
    assert amount(milk, "trans_fat_g") == 0.118
    assert ("250 ml", 257.819) in milk.portions

    bread = cnf_foods["4066"]
    assert amount(bread, "folate_ug_dfe") == 177.9  # 435 DFE, not 417 total folate (109)
    assert amount(bread, "sodium_mg") == 513
    assert ("1 slice", 36.0) in bread.portions
    assert set(bread.nutrients) <= set(BY_CODE)  # niacin equivalents (409), amino acids etc. don't leak in


def test_cnf_assumed_zero_is_kept_with_note(cnf_foods):
    eulachon = cnf_foods["3241"]
    assert eulachon.nutrients["fiber_g"] == (0.0, "CNF; Nutrient value is an assumed zero")
    assert eulachon.nutrients["sugars_g"] == (0.0, "CNF; Nutrient value is an assumed zero")


def test_cnf_fallbacks(cnf_foods):
    eulachon = cnf_foods["3241"]  # no DFE (435): total folate with the caveat
    assert "total folate; equals DFE only" in note(eulachon, "folate_ug_dfe")
    bran = cnf_foods["1260"]  # total folate 60 is all added folic acid: not a DFE value, so left out
    assert "folate_ug_dfe" not in bran.nutrients
    pasta = cnf_foods["4516"]  # no RAE (320): retinol + beta-carotene/12
    assert "RAE = retinol + beta-carotene/12" in note(pasta, "vitamin_a_ug")
