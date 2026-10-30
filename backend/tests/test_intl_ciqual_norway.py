"""Ciqual (France) and Matvaretabellen (Norway) parsers, on excerpts of the published files."""

import re
import shutil
from pathlib import Path

import pytest

from app.services.datasets import BY_KEY
from app.sources.intl import ciqual, matvaretabellen

FIXTURES = Path(__file__).parent / "fixtures" / "intl"
CIQUAL = FIXTURES / "ciqual"
NORWAY = FIXTURES / "matvaretabellen"


def ciqual_files(root: Path = CIQUAL) -> dict[str, Path]:
    return {"alim": root / "alim.xml", "compo": root / "compo.xml", "const": root / "const.xml", "groups": root / "groups.xml"}


def norway_files(with_sources: bool = True) -> dict[str, Path]:
    files = {"foods": NORWAY / "foods.json", "nutrients": NORWAY / "nutrients.json", "groups": NORWAY / "food-groups.json"}
    if with_sources:
        files["sources"] = NORWAY / "sources.json"
    return files


@pytest.fixture(scope="module")
def cq():
    return {f.source_id: f for f in ciqual.parse(ciqual_files())}


@pytest.fixture(scope="module")
def no():
    return {f.source_id: f for f in matvaretabellen.parse(norway_files())}


def amount(food, code):
    return food.nutrients[code][0]


def why(food, code):
    return food.nutrients[code][1]


# --- Ciqual -----------------------------------------------------------------------------


def test_ciqual_food_metadata(cq):
    assert set(cq) == {"1032", "2002", "9811", "13039", "19024"}
    apple = cq["13039"]
    assert apple.source == "ciqual" and apple.name == "Apple, flesh and skin, raw"
    assert apple.data_type == "Ciqual 2025" and apple.state == "raw" and apple.trust_level == "analytical"
    assert apple.category == "Fruits, vegetables, legumes and nuts"
    assert cq["9811"].category == "Cereal products" and cq["9811"].state == "cooked"
    assert apple.citation == f"{BY_KEY['intl_ciqual'].attribution}. Food 13039."
    assert "doi.org/10.57745/RDMHWY" in apple.citation


def test_ciqual_values_units_and_confidence(cq):
    apple = cq["13039"]
    # "<teneur> 0,25 </teneur>": padded, decimal comma.
    assert amount(apple, "protein_g") == pytest.approx(0.25)
    assert why(apple, "protein_g") == "Ciqual; confidence B"
    assert amount(apple, "energy_kcal") == 54  # 328, EU Regulation kcal (not 333, Jones-factor energy)
    assert why(apple, "energy_kcal") == "Ciqual; confidence D; EU Regulation 1169/2011 factors"
    assert amount(apple, "sodium_mg") == pytest.approx(1.5)
    assert amount(apple, "vitamin_c_mg") == pytest.approx(4.6)
    assert amount(apple, "vitamin_k_ug") == pytest.approx(1.78)
    milk = cq["19024"]
    assert amount(milk, "sat_fat_g") == pytest.approx(2.25)
    assert amount(milk, "iodine_ug") == pytest.approx(12.4)  # µg/100g
    assert amount(milk, "vitamin_d_ug") == pytest.approx(0.06)


def test_ciqual_markers(cq):
    apple, burger, juice = cq["13039"], cq["1032"], cq["2002"]
    # "< 10" -> 0, with the limit recorded.
    assert amount(apple, "selenium_ug") == 0
    assert why(apple, "selenium_ug") == "Ciqual; confidence A; below limit (<10)"
    # "traces" -> 0, noted.
    assert amount(burger, "vitamin_d_ug") == 0 and why(burger, "vitamin_d_ug").endswith("; trace")
    assert amount(juice, "mono_fat_g") == 0 and "trace" in why(juice, "mono_fat_g")
    # "-" -> unknown, left out (not zero).
    assert "vitamin_e_mg" not in juice.nutrients


def test_ciqual_carbohydrate_is_available_plus_fibre(cq):
    apple = cq["13039"]
    assert amount(apple, "carbs_g") == pytest.approx(11.6 + 1.4)
    assert why(apple, "carbs_g") == "Ciqual; available carbohydrate + fibre (confidence B + A)"
    assert amount(apple, "fiber_g") == pytest.approx(1.4)
    assert amount(cq["9811"], "carbs_g") == pytest.approx(31.4 + 2.2)


def test_ciqual_vitamin_a_is_rae_from_retinol_and_beta_carotene(cq):
    assert amount(cq["13039"], "vitamin_a_ug") == pytest.approx(0 + 21.4 / 12)
    assert why(cq["13039"], "vitamin_a_ug") == "Ciqual; RAE = retinol + beta-carotene/12 (confidence C + B)"
    # Beta-carotene "< 30" counts as 0; Ciqual's own 51104 (61,8) uses half the limit and is not used.
    assert amount(cq["1032"], "vitamin_a_ug") == pytest.approx(60.5)
    assert amount(cq["2002"], "vitamin_a_ug") == pytest.approx(380 / 12)


def test_ciqual_vitamin_e_only_alpha_tocopherol(cq):
    assert amount(cq["1032"], "vitamin_e_mg") == pytest.approx(0.31)  # 71010 alpha-tocopherol
    assert "vitamin_e_mg" not in cq["2002"].nutrients  # only 53100 "Vitamin E" (unspecified) = 2


def test_ciqual_folate(cq):
    # 56702 DFE is used as is (here with added folic acid).
    assert amount(cq["1032"], "folate_ug_dfe") == pytest.approx(21.6)
    assert why(cq["1032"], "folate_ug_dfe") == "Ciqual; confidence A"
    # Total folate (56700) with no folic acid stands in for DFE, with the caveat.
    assert amount(cq["9811"], "folate_ug_dfe") == pytest.approx(5.2)
    assert "total folate as DFE" in why(cq["9811"], "folate_ug_dfe")
    # A multivitamin juice's total folate includes folic acid that isn't reported separately: skipped.
    assert "folate_ug_dfe" not in cq["2002"].nutrients


def test_ciqual_total_folate_skipped_with_folic_acid(tmp_path):
    for name in ("alim.xml", "const.xml", "groups.xml"):
        shutil.copy(CIQUAL / name, tmp_path / name)
    text = (CIQUAL / "compo.xml").read_text(encoding="utf-8-sig")
    # Food 1032 reports DFE and folic acid 5,7; give it total folate instead of DFE.
    text, n = re.subn(r"(<alim_code> 1032 </alim_code>\s+<const_code> )56702", r"\g<1>56700", text)
    assert n == 1
    (tmp_path / "compo.xml").write_text(text, encoding="utf-8-sig")
    foods = {f.source_id: f for f in ciqual.parse(ciqual_files(tmp_path))}
    assert "folate_ug_dfe" not in foods["1032"].nutrients
    assert foods["9811"].nutrients["folate_ug_dfe"][0] == pytest.approx(5.2)


# --- Matvaretabellen ---------------------------------------------------------------------


def test_norway_food_metadata(no):
    assert set(no) == {"01.236", "05.130", "05.394", "06.178", "06.758", "10.137"}
    apple = no["06.758"]
    assert apple.source == "matvaretabellen" and apple.name == "Apple, unspecified, raw"
    assert apple.data_type == "Matvaretabellen" and apple.state == "raw"
    assert apple.category == "Fruit and berries"  # top-level group of 13.2 "Fruit"
    assert no["05.130"].category == "Cereals, bread and cakes" and no["05.130"].state == "cooked"
    assert apple.source_url == "https://www.matvaretabellen.no/en/apple-unspecified-raw/"
    assert apple.citation == ("Matvaretabellen. Mattilsynet (Norwegian Food Safety Authority). www.matvaretabellen.no. "
                              "Licensed under CC BY 4.0. Food 06.758.")
    assert apple.citation.startswith(BY_KEY["intl_matvaretabellen"].attribution)


def test_norway_portions(no):
    assert no["06.758"].portions == [("1 piece (medium)", 125.0), ("1 piece (small)", 90.0), ("1 piece (large)", 165.0)]
    assert ("1 decilitre", 100.0) in no["01.236"].portions and ("1 glass", 200.0) in no["01.236"].portions


def test_norway_values_and_sources(no):
    milk = no["01.236"]
    assert amount(milk, "energy_kcal") == 64  # published kcal (EU factors), not kJ / 4.184
    assert why(milk, "energy_kcal") == ("Matvaretabellen; source MI0115: Energy calculated according to "
                                       "Regulation (EU) 1169/2011 (kcal)")
    assert amount(milk, "protein_g") == pytest.approx(3.4)
    assert amount(milk, "sodium_mg") == 40
    assert amount(milk, "iodine_ug") == 16
    beans = no["06.178"]
    assert amount(beans, "protein_g") == pytest.approx(19.9)
    assert "USDA National Nutrient Datab" in why(beans, "protein_g")  # values taken from USDA SR28
    cereal = no["05.394"]
    assert amount(cereal, "fiber_g") == 7
    assert "vitamin_c_mg" not in cereal.nutrients  # sourceId 10: content not known
    assert amount(cereal, "added_sugars_g") == 7  # "Sukker" (SUGAD), separate from total sugars
    assert amount(cereal, "sugars_g") == pytest.approx(8.8)
    for food in no.values():
        assert all(len(d) <= 120 for _, d in food.nutrients.values())


def test_norway_without_sources_file_records_ids():
    beans = next(f for f in matvaretabellen.parse(norway_files(with_sources=False)) if f.source_id == "06.178")
    assert why(beans, "protein_g") == "Matvaretabellen; source 460g"


def test_norway_carbohydrate_is_available_plus_fibre(no):
    assert amount(no["06.758"], "carbs_g") == pytest.approx(10.1 + 3.0)
    assert why(no["06.758"], "carbs_g") == "Matvaretabellen; available carbohydrate + fibre"
    assert amount(no["06.178"], "carbs_g") == pytest.approx(50.2 + 13.0)


def test_norway_vitamin_a_rae_not_re_and_no_vitamin_e(no):
    beans = no["06.178"]
    assert amount(beans, "vitamin_a_ug") == 1  # "Vit A" RAE 1, not "Vit A RE" 2
    assert "factor 1/12" in why(beans, "vitamin_a_ug")
    assert amount(no["01.236"], "vitamin_a_ug") == 25
    assert all("vitamin_e_mg" not in f.nutrients for f in no.values())  # only alpha-TE (mg-ATE) is published


def test_norway_folate_and_supplements(no):
    assert amount(no["06.178"], "folate_ug_dfe") == 622
    assert why(no["06.178"], "folate_ug_dfe").startswith("Matvaretabellen; total folate as DFE (no folic acid assumed)")
    supplement = no["10.137"]
    assert "folate_ug_dfe" not in supplement.nutrients  # folic acid
    assert "energy_kcal" not in supplement.nutrients  # no energy published
    assert amount(supplement, "vitamin_c_mg") == 450


def test_norway_below_quantification_limit_is_zero_with_reason(no):
    cereal = no["05.394"]
    assert amount(cereal, "trans_fat_g") == 0 and amount(cereal, "cholesterol_mg") == 0
    assert why(cereal, "cholesterol_mg") == ("Matvaretabellen; source 60a: Estimated as zero value when the analysed "
                                             "value is below the limit of quantification")
