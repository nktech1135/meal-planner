"""Danish Food Composition Database and Swiss Food Composition Database parsers, on excerpts of the published files."""

from pathlib import Path

import openpyxl
import pytest

from app.sources.intl import dk_fcdb, swiss

FIXTURES = Path(__file__).parent / "fixtures" / "intl"
DK = FIXTURES / "dk_fcdb" / "fcdb61_excerpt.xlsx"
CH = FIXTURES / "swiss" / "swiss_fcdb71_excerpt.xlsx"


@pytest.fixture(scope="module")
def dk():
    return {f.source_id: f for f in dk_fcdb.parse({"data": DK})}


@pytest.fixture(scope="module")
def ch():
    return {f.source_id: f for f in swiss.parse({"data": CH})}


def amount(food, code):
    return food.nutrients[code][0]


def why(food, code):
    return food.nutrients[code][1]


# --- Denmark ---------------------------------------------------------------------------------


def test_dk_food_metadata(dk):
    assert set(dk) == {"2", "6", "174", "251", "263", "1973"}
    apple = dk["2"]
    assert apple.source == "dk_fcdb" and apple.name == "Apple, raw, all varieties"
    assert apple.data_type == "Danish FCDB 6.1" and apple.trust_level == "analytical" and apple.state == "raw"
    assert apple.category == "Fruit, berries and their products: Pome fruit"
    assert apple.citation == ("The Danish Food Composition Database (http://fcdb.fooddata.dk), version 6.1, May 2026, The "
                              "Food Institute, Technical University of Denmark. Licensed under CC BY 4.0. Food 2.")
    assert apple.citation.startswith(dk_fcdb.ATTRIBUTION)
    rice = dk["1973"]
    assert rice.state == "cooked" and rice.cooking_method == "boiled"
    assert rice.category == "Cereals and starch products: Grain and groats"
    assert dk["174"].category == "Ready meals, fastfood and composite foods: Biscuits and cookies"  # leading space trimmed


def test_dk_values_and_sources(dk):
    apple, milk = dk["2"], dk["6"]
    assert amount(apple, "energy_kcal") == pytest.approx(55.0647, abs=1e-4)  # published kcal, not 232.5 kJ / 4.184
    assert why(apple, "energy_kcal") == "Danish FCDB 6.1; source 1003: Value calculated by converting various analytical data"
    assert amount(apple, "protein_g") == pytest.approx(0.26936, abs=1e-5)
    assert why(apple, "protein_g") == "Danish FCDB 6.1; sources 1068, 1842, 1859, 2179"
    assert amount(apple, "sodium_mg") == pytest.approx(0.6012)  # sodium, not "Salt labelling"
    assert amount(apple, "vitamin_c_mg") == pytest.approx(8.2627, abs=1e-4)
    assert amount(apple, "niacin_mg") == pytest.approx(0.12284)  # preformed niacin, not niacin equivalents (0.166)
    assert "preformed niacin" in why(apple, "niacin_mg")
    assert amount(milk, "calcium_mg") == pytest.approx(115.8, abs=0.1)
    assert amount(milk, "iodine_ug") == pytest.approx(10.73, abs=0.01)
    # "Natural zero value for content. Not analyzed" is a published 0, with its source recorded.
    assert amount(milk, "fiber_g") == 0
    assert why(milk, "fiber_g") == "Danish FCDB 6.1; source 1655: Natural zero value for content. Not analyzed"
    # A value without a source ("NULL") carries only the database name.
    assert why(dk["174"], "fiber_g") == "Danish FCDB 6.1"
    assert milk.portions == [("100 mL", 103.1)]  # density 1.031 g/ml
    assert apple.portions == []
    for food in dk.values():
        assert all(len(d) <= 120 for _, d in food.nutrients.values())


def test_dk_carbohydrate_by_difference(dk):
    apple = dk["2"]
    assert amount(apple, "carbs_g") == pytest.approx(14.2613, abs=1e-4)  # = 12.0524 available + 2.2089 fibre
    assert why(apple, "carbs_g").startswith("Danish FCDB 6.1; by difference")
    assert amount(apple, "fiber_g") == pytest.approx(2.2089, abs=1e-4)
    # Olives: by difference (4.69) is below the fibre (6.2); available carbohydrate is clamped to 0. Used as published.
    assert amount(dk["251"], "carbs_g") == pytest.approx(4.69)


def test_dk_carbohydrate_falls_back_to_available_plus_fibre(tmp_path):
    wb = openpyxl.load_workbook(DK)
    ws = wb["Data_Normalised"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == 2 and row[3].value == 170:  # no "Carbohydrate by difference" for the apple
            row[7].value = "NULL"
    wb.save(tmp_path / "data.xlsx")
    apple = next(f for f in dk_fcdb.parse({"data": tmp_path / "data.xlsx"}) if f.source_id == "2")
    assert amount(apple, "carbs_g") == pytest.approx(12.0524 + 2.2089, abs=1e-4)
    assert why(apple, "carbs_g") == "Danish FCDB 6.1; available carbohydrate + fibre"


def test_dk_vitamin_a_is_rae_never_re(dk):
    assert amount(dk["2"], "vitamin_a_ug") == pytest.approx(0 + 25 / 12)  # Vitamin A (RE) is 4.17
    assert why(dk["2"], "vitamin_a_ug") == "Danish FCDB 6.1; RAE = retinol + beta-carotene/12"
    assert amount(dk["6"], "vitamin_a_ug") == pytest.approx(30.4036 + 16 / 12, abs=1e-3)  # RE is 33.07
    assert "vitamin_a_ug" not in dk["174"].nutrients  # only RE (279) is published


def test_dk_vitamin_e_is_alpha_tocopherol_never_te(dk):
    assert amount(dk["2"], "vitamin_e_mg") == pytest.approx(0.25429, abs=1e-5)
    assert "vitamin_e_mg" not in dk["251"].nutrients  # only "Vitamin E" in alpha-TE (6.1) is published


def test_dk_vitamin_d_excludes_25_hydroxy(dk):
    milk = dk["6"]
    # Published Vitamin D 0.03925 = D3 0.009175 + D2 0.00345 + 2.5 x 25-OH D3 0.007525.
    assert amount(milk, "vitamin_d_ug") == pytest.approx(0.009175 + 0.00345)
    assert "D3 + D2 (excludes 25-OH D)" in why(milk, "vitamin_d_ug")
    assert amount(dk["2"], "vitamin_d_ug") == 0  # no 25-hydroxy D: Vitamin D as published


def test_dk_folate(dk):
    assert amount(dk["2"], "folate_ug_dfe") == 9
    assert why(dk["2"], "folate_ug_dfe") == ("Danish FCDB 6.1; total folate as DFE (no folic acid assumed); "
                                            "source 1305: Monitoring - Fruits and vegetables, 4th Cycle")
    assert why(dk["174"], "folate_ug_dfe") == "Danish FCDB 6.1; total folate as DFE (no folic acid assumed)"
    krispies = dk["263"]
    assert "folate_ug_dfe" not in krispies.nutrients  # 292 µg: fortified breakfast cereal
    assert amount(krispies, "niacin_mg") == pytest.approx(16.8)


@pytest.mark.parametrize("name,folic_acid", [
    ("Baby food, infant formula, low iron content, powder", True),
    ("Oatmilk, with added calcium and vitamins", True),
    ("Plant margarine, 80%, fry/bake, enriched with A-vitamin", True),
    ("Corn flakes, average values", True),
    ("Oat drink, unfortified", False),
    ("Oats, rolled, not enriched", False),
    ("Soy drink, with added calcium", False),
    ("Salt, sea salt (no iodine fortification)", False),
])
def test_dk_folic_acid_names(name, folic_acid):
    assert bool(dk_fcdb.FOLIC_ACID.search(name)) is folic_acid


# --- Switzerland -----------------------------------------------------------------------------


def test_swiss_food_metadata(ch):
    assert set(ch) == {"10533", "273", "378", "290", "14130", "1066", "62", "524"}
    apple = ch["378"]
    assert apple.source == "swiss" and apple.name == "Apple, fresh" and apple.trust_level == "analytical"
    assert apple.data_type == "Swiss FCDB 7.1" and apple.category == "Fruit: Fresh fruit"
    assert apple.citation == ("Swiss Food Composition Database V 7.1 (01.07.2026), Federal Food Safety and Veterinary Office "
                              "FSVO, www.naehrwertdaten.ch. Food 378.")
    assert apple.citation.startswith(swiss.ATTRIBUTION)
    assert ch["290"].category == "Eggs"
    rice = ch["1066"]
    assert rice.state == "cooked" and rice.category == "Cereal products, pulses and potatoes: Rice"
    assert ch["62"].portions == [("100 mL", 103.0)] and ch["14130"].portions == [("100 mL", 105.0)]
    assert apple.portions == []


def test_swiss_branded_foods_are_label_data(ch):
    water = ch["524"]
    assert water.name == "Mineral water, Perrier" and water.trust_level == "label"
    assert water.data_type == "Swiss FCDB 7.1 (branded)" and water.category == "Non-alcoholic beverages: Mineral water"
    assert amount(water, "calcium_mg") == 16
    assert why(water, "calcium_mg").startswith("Swiss FCDB 7.1; source 3206: Verband Schweizerischer Mineralquellen")
    assert "iodine_ug" not in water.nutrients  # n.d.


def test_swiss_values_and_derivations(ch):
    apple, milk, rice = ch["378"], ch["62"], ch["1066"]
    assert amount(apple, "energy_kcal") == 52  # published kcal, not 222 kJ / 4.184
    assert why(apple, "energy_kcal") == "Swiss FCDB 7.1; calculated"
    assert why(apple, "fat_g") == ("Swiss FCDB 7.1; source 2277: Anses - Table de composition nutritionnelle des aliments "
                                   "Ciqual 2020")
    assert amount(apple, "vitamin_c_mg") == pytest.approx(7.2)
    assert why(apple, "vitamin_c_mg") == "Swiss FCDB 7.1; sources 1670, 1692, 2277"
    assert amount(apple, "niacin_mg") == pytest.approx(0.08)  # preformed niacin; niacin equivalents are 0.13
    assert amount(milk, "protein_g") == pytest.approx(3.2)
    assert why(milk, "protein_g") == ("Swiss FCDB 7.1; N × 6.25; estimated; source 1662: Schweizerische Gesellschaft für "
                                      "Ernährung SGE, Bern, Schweiz, 2018")
    assert amount(milk, "iodine_ug") == 10 and amount(milk, "vitamin_e_mg") == pytest.approx(0.11)
    assert amount(rice, "sodium_mg") == 530  # sodium as published; salt (1.3 g) is not used
    assert why(rice, "sodium_mg") == "Swiss FCDB 7.1; recipe calculation"
    for food in ch.values():
        assert all(len(d) <= 120 for _, d in food.nutrients.values())


def test_swiss_markers(ch):
    almond, egg, agar = ch["273"], ch["290"], ch["10533"]
    assert amount(almond, "vitamin_c_mg") == 0 and why(almond, "vitamin_c_mg").endswith("; below limit (<0.5)")
    assert amount(egg, "vitamin_c_mg") == 0 and why(egg, "vitamin_c_mg").endswith("; trace")
    for code in ("vitamin_c_mg", "folate_ug_dfe", "vitamin_a_ug", "vitamin_e_mg", "iodine_ug"):
        assert code not in agar.nutrients  # n.d.: unknown, not zero


def test_swiss_carbohydrate_is_available_plus_fibre(ch):
    assert amount(ch["378"], "carbs_g") == pytest.approx(11.6 + 1.4)
    assert why(ch["378"], "carbs_g") == "Swiss FCDB 7.1; available carbohydrate + fibre"
    assert amount(ch["1066"], "carbs_g") == pytest.approx(25.8 + 0.3)
    assert amount(ch["10533"], "carbs_g") == pytest.approx(0 + 74.1)


def test_swiss_vitamin_a_rae_not_re(ch):
    assert amount(ch["62"], "vitamin_a_ug") == 47  # RE is 49
    assert why(ch["62"], "vitamin_a_ug") == "Swiss FCDB 7.1; RAE as published; calculated"
    assert amount(ch["378"], "vitamin_a_ug") == 2  # RE is 4


def test_swiss_vitamin_d_and_folate_exclusions(ch):
    egg, oat = ch["290"], ch["14130"]
    assert "vitamin_d_ug" not in egg.nutrients  # egg vitamin D counts 25-hydroxy D3
    assert amount(egg, "folate_ug_dfe") == 67
    assert amount(ch["62"], "vitamin_d_ug") == pytest.approx(0.1)
    assert "folate_ug_dfe" not in oat.nutrients  # fortified with vitamins
    assert amount(oat, "vitamin_d_ug") == pytest.approx(0.9)
    assert amount(ch["378"], "folate_ug_dfe") == 6
    assert why(ch["378"], "folate_ug_dfe").startswith("Swiss FCDB 7.1; total folate as DFE (no folic acid assumed)")


def test_swiss_category_format():
    assert swiss.category("Savoury snacks/Chips/Crisps") == "Savoury snacks: Chips/Crisps"
    assert swiss.category("Fruit/Fruit juices;Non-alcoholic beverages/Fruit and vegetable juices") == "Fruit: Fruit juices"
    assert swiss.category(None) is None
