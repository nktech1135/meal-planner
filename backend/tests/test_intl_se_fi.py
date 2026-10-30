"""Livsmedelsdatabasen (Sweden) and Fineli (Finland) parsers, on excerpts of the published data."""

import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.sources.intl import fineli, se_livsmedel

FIXTURES = Path(__file__).parent / "fixtures" / "intl"
SWEDEN = FIXTURES / "se_livsmedel" / "livsmedel_excerpt.json"
FINELI = FIXTURES / "fineli" / "fineli_rel20_excerpt.zip"


@pytest.fixture(scope="module")
def se():
    return {f.source_id: f for f in se_livsmedel.parse({"data": SWEDEN})}


@pytest.fixture(scope="module")
def fi():
    return {f.source_id: f for f in fineli.parse({"zip": FINELI})}


def amount(food, code):
    return food.nutrients[code][0]


def why(food, code):
    return food.nutrients[code][1]


# --- Fineli ------------------------------------------------------------------------------


def test_fineli_food_metadata(fi):
    assert set(fi) == {"11060", "689", "1370", "1009", "606", "29071", "163"}
    apple = fi["11060"]
    assert apple.source == "fineli" and apple.name == "Apple, domestic, without skin"
    assert apple.data_type == "Fineli Release 20" and apple.trust_level == "analytical"
    assert apple.state == "raw"  # PROCESS "RAW" (no treatment); the name doesn't say
    assert apple.category == "Fruits"  # food-use class FRUFRESH (parent: "Fruit and berry dishes")
    assert apple.source_url == "https://fineli.fi/fineli/en/elintarvikkeet/11060"
    assert apple.citation == ("Finnish Institute for Health and Welfare, Fineli. Finnish food composition database, "
                              "Release 20 (2019). Licensed under CC BY 4.0. Food 11060.")
    assert apple.citation.startswith(fineli.ATTRIBUTION.rstrip("."))
    assert fi["1370"].name == "Rice, boiled without salt" and fi["1370"].state == "cooked"
    assert (fi["1009"].state, fi["1009"].cooking_method) == ("cooked", "baked")  # PROCESS "BAK"
    assert fi["689"].state is None and fi["689"].category == "Milks >2% fat"
    assert fi["606"].name == "Milk, 0% fat, i ug added vitamin D"  # Fineli's own "I UG"


def test_fineli_portions(fi):
    assert fi["11060"].portions == [("1 decilitre", 65.0), ("1 portion (small)", 90.0), ("1 portion (medium)", 180.0),
                                    ("1 portion (large)", 260.0)]
    assert ("1 piece (medium)", 35.0) in fi["1009"].portions


def test_fineli_values_units_and_decimal_commas(fi):
    apple, milk = fi["11060"], fi["689"]
    assert amount(apple, "protein_g") == pytest.approx(0.19)  # "0,19"
    assert amount(apple, "energy_kcal") == pytest.approx(169.58 / 4.184)  # ENERC "169,58" kJ only
    assert why(apple, "energy_kcal") == "Fineli; converted from kJ"
    assert amount(apple, "sodium_mg") == pytest.approx(0.92)
    assert amount(apple, "vitamin_c_mg") == 8
    assert amount(milk, "fat_g") == pytest.approx(3.5)
    assert why(milk, "fat_g") == "Fineli; calculated on component profile"  # METHTYPE P
    assert amount(milk, "sat_fat_g") == pytest.approx(2.2276)
    assert amount(milk, "iodine_ug") > 0 and amount(milk, "selenium_ug") > 0
    assert amount(fi["163"], "thiamin_mg") == pytest.approx(1.2)
    for food in fi.values():
        assert all(len(d) <= 120 for _, d in food.nutrients.values())


def test_fineli_carbohydrate_by_difference(fi):
    # CHOCDF (by difference) is our definition and wins over CHOAVL + FIBC.
    apple = fi["11060"]
    assert amount(apple, "carbs_g") == pytest.approx(11.242)
    assert amount(apple, "fiber_g") == pytest.approx(1.8)  # FIBC "fibre, total"
    assert why(apple, "carbs_g") == "Fineli; summation from constituent components"
    # Release 20's boiled rice: CHOCDF 31.2 (from analysed water) but available carbohydrate only 20.6.
    assert amount(fi["1370"], "carbs_g") == pytest.approx(31.158)


def test_fineli_available_carbohydrate_fallback(tmp_path):
    excerpt = tmp_path / "excerpt.zip"
    with zipfile.ZipFile(FINELI) as zin, zipfile.ZipFile(excerpt, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "component_value.csv":
                data = b"\r\n".join(line for line in data.split(b"\r\n") if not line.startswith(b"11060;CHOCDF;"))
            zout.writestr(info, data)
    apple = next(f for f in fineli.parse({"zip": excerpt}) if f.source_id == "11060")
    assert amount(apple, "carbs_g") == pytest.approx(8.31 + 1.8)
    assert why(apple, "carbs_g") == "Fineli; available carbohydrate + fibre"
    assert "available_carbs_g" not in apple.nutrients


def test_fineli_vitamin_a_is_published_rae(fi):
    # VITA is RAE including other provitamin A carotenoids: 1,419 > 0 + 11,6/12.
    assert amount(fi["11060"], "vitamin_a_ug") == pytest.approx(1.419)
    assert amount(fi["689"], "vitamin_a_ug") == pytest.approx(28.56)


def test_fineli_vitamin_e_niacin_and_unmapped_components(fi):
    milk, cereal = fi["689"], fi["163"]
    assert amount(milk, "vitamin_e_mg") == pytest.approx(0.065)  # VITE alpha-tocopherol
    assert amount(cereal, "niacin_mg") == pytest.approx(14.9)  # NIA, not NIAEQ 16.904
    for food in fi.values():
        assert "vitamin_b6_mg" not in food.nutrients  # VITPYRID: as pyridoxine hydrochloride
        assert "vitamin_k_ug" not in food.nutrients  # VITK: total vitamin K
        assert "mono_fat_g" not in food.nutrients  # FAMCIS: cis isomers only
    assert amount(cereal, "sodium_mg") == 700  # NA, not NACL 1783.6


def test_fineli_vitamin_d_without_25_hydroxy(fi):
    assert amount(fi["689"], "vitamin_d_ug") == 1
    assert "vitamin_d_ug" not in fi["606"].nutrients  # MI0354: includes 25-hydroxy-D3
    assert "vitamin_d_ug" not in fi["29071"].nutrients  # a recipe made with food 606
    assert amount(fi["1009"], "vitamin_d_ug") == 0


def test_fineli_folate(fi):
    assert amount(fi["689"], "folate_ug_dfe") == 6
    assert why(fi["689"], "folate_ug_dfe") == "Fineli; total folate as DFE (no folic acid assumed); calculated, generic"
    assert amount(fi["29071"], "folate_ug_dfe") == pytest.approx(4.23)
    assert "folate_ug_dfe" not in fi["163"].nutrients  # corn flakes: 166 µg, mostly folic acid


# --- Livsmedelsdatabasen -----------------------------------------------------------------


def test_sweden_food_metadata(se):
    assert set(se) == {"588", "123", "2515", "706", "257", "1", "347", "164", "31", "1881"}
    apple = se["588"]
    assert apple.source == "se_livsmedel" and apple.name == "Apple w/ skin" and apple.trust_level == "analytical"
    assert apple.data_type == "Livsmedelsdatabasen 2026-07-01" and apple.category == "Fruit, berry"
    assert apple.source_url == "https://soknaringsinnehall.livsmedelsverket.se/Home/FoodDetails/588"
    assert apple.citation == ("The Swedish Food Agency food database (Livsmedelsverket), version 2026-07-01. "
                              "Licensed under CC BY 4.0. Food 588.")
    assert se_livsmedel.attribution(None) == se_livsmedel.ATTRIBUTION
    assert apple.state is None and apple.portions == []  # the database has no portion sizes
    assert (se["2515"].state, se["2515"].cooking_method) == ("cooked", "boiled")  # from the name
    assert se["257"].state == "cooked"  # tillagningsmetod "COOKED BY DRY HEAT"
    assert se["164"].name == "Crisp bread wholegrain wheat w/ poppy seeds fibre 5.5%"  # trailing space dropped


def test_sweden_values_and_units(se):
    milk, apple = se["123"], se["588"]
    assert amount(milk, "energy_kcal") == 60  # published kcal, not kJ / 4.184
    assert why(milk, "energy_kcal") == "Livsmedelsdatabasen"
    assert amount(milk, "protein_g") == pytest.approx(3.6)
    assert amount(milk, "iodine_ug") == 22  # "Iodide, I" (µg)
    assert amount(milk, "vitamin_d_ug") == 1  # D2 + D3; VITD_x (with 25-OH-D3) isn't used
    assert amount(milk, "vitamin_b6_mg") == pytest.approx(0.05)
    assert amount(milk, "vitamin_e_mg") == pytest.approx(0.1)  # alpha-tocopherol
    assert amount(apple, "added_sugars_g") == 0 and amount(apple, "sugars_g") == pytest.approx(9.9)
    assert amount(se["2515"], "sodium_mg") == 209 and amount(se["2515"], "niacin_mg") == pytest.approx(0.16)
    for food in se.values():
        assert "thiamin_mg" not in food.nutrients  # THIACLHCL: as thiamin chloride hydrochloride
        assert all(len(d) <= 120 for _, d in food.nutrients.values())


def test_sweden_carbohydrate_is_available_plus_fibre(se):
    assert amount(se["588"], "carbs_g") == pytest.approx(10.6 + 2.3)
    assert why(se["588"], "carbs_g") == "Livsmedelsdatabasen; available carbohydrate + fibre"
    assert amount(se["588"], "fiber_g") == pytest.approx(2.3)
    assert amount(se["2515"], "carbs_g") == pytest.approx(24.6 + 0.3)


def test_sweden_value_types(se):
    tallow, corn, butter, bread = se["1"], se["347"], se["31"], se["164"]
    assert amount(tallow, "zinc_mg") == 0 and why(tallow, "zinc_mg") == "Livsmedelsdatabasen; below limit of detection"
    # A below-limit value that carries a number: that is the limit, recorded, and the amount is 0.
    assert amount(corn, "fat_g") == 0
    assert why(corn, "fat_g") == "Livsmedelsdatabasen; below limit of quantification (<1.9 g)"
    assert why(corn, "selenium_ug") == "Livsmedelsdatabasen; below limit of quantification (<1 µg)"
    assert amount(butter, "zinc_mg") == 0 and why(butter, "zinc_mg") == "Livsmedelsdatabasen; trace"
    assert amount(tallow, "vitamin_c_mg") == 0 and why(tallow, "vitamin_c_mg").endswith("; logical zero")
    assert "cholesterol_mg" not in bread.nutrients  # value type N "Unknown"


def test_sweden_vitamin_a(se):
    # "Retinol equivalents" computed as RAE (factor 1/12 and 1/24): used as published.
    assert amount(se["1"], "vitamin_a_ug") == pytest.approx(31.3)
    assert amount(se["31"], "vitamin_a_ug") == pytest.approx(896.2)
    assert amount(se["257"], "vitamin_a_ug") == pytest.approx(81.5)  # recipe sum of RAE values
    # Food 1881's value uses the RE factor 1/6 (0.5): RAE is derived from retinol + beta-carotene/12 instead.
    assert amount(se["1881"], "vitamin_a_ug") == pytest.approx(0.25)
    assert why(se["1881"], "vitamin_a_ug") == "Livsmedelsdatabasen; RAE = retinol + beta-carotene/12"


def test_sweden_folate(se):
    assert amount(se["588"], "folate_ug_dfe") == pytest.approx(2.9)
    assert why(se["588"], "folate_ug_dfe") == "Livsmedelsdatabasen; total folate as DFE (no folic acid assumed)"
    assert amount(se["123"], "folate_ug_dfe") == pytest.approx(8.8)  # milk: fortified with vitamins A and D only
    assert "folate_ug_dfe" not in se["706"].nutrients  # fortified corn flakes: 166 µg, mostly folic acid


def _export_workbook() -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["The Swedish Food Agency food database, version 2026-07-01"])
    ws.append(["Nutrient contents per 100 g food."])
    ws.append(["Food Name", "Food Number", "Filter group", "Energy (kcal)"])
    ws.append(["Apple w/ skin", 588, "Fruit, berry", 48])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sweden_fetch_all_assembles_the_data_file(monkeypatch, tmp_path):
    monkeypatch.setattr(se_livsmedel.time, "sleep", lambda s: None)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        if request.method == "POST":
            assert "SokNaringsinnehall.Sprak=Engelska" in request.headers["cookie"]
            return httpx.Response(200, content=_export_workbook())
        if request.url.path.endswith("/livsmedel"):
            return httpx.Response(200, json={"_meta": {"totalRecords": 1},
                                             "livsmedel": [{"nummer": 588, "namn": "Apple w/ skin"}]})
        if len([s for s in seen if s[1].endswith("/naringsvarden")]) == 1:
            return httpx.Response(503)  # retried
        return httpx.Response(200, json=[{"namn": "Protein", "euroFIRkod": "PROT", "varde": 0.3, "enhet": "g",
                                          "vardetypkod": "AV", "publikation": "dropped"}])

    progress = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        data = se_livsmedel.fetch_all(client, lambda m, d=None, t=None: progress.append((m, d, t)))
    assert data["version"] == "2026-07-01" and data["groups"] == {"588": "Fruit, berry"}
    assert data["foods"] == [{"nummer": 588, "namn": "Apple w/ skin"}]
    assert data["nutrients"] == {"588": [{"namn": "Protein", "euroFIRkod": "PROT", "varde": 0.3, "enhet": "g",
                                          "vardetypkod": "AV"}]}
    assert seen[0][2]["sprak"] == "2" and seen[-1][2] == {"sprak": "2"}
    assert progress[-1] == ("Fetched nutrients for 1 of 1 Swedish foods…", 1, 1)
    # The assembled structure is what the parser reads.
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    food = next(se_livsmedel.parse({"data": tmp_path / "data.json"}))
    assert food.nutrients["protein_g"][0] == pytest.approx(0.3) and food.category == "Fruit, berry"


def test_sweden_fetch_all_without_the_export(monkeypatch):
    monkeypatch.setattr(se_livsmedel.time, "sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(500)
        if request.url.path.endswith("/livsmedel"):
            return httpx.Response(200, json={"livsmedel": [{"nummer": 1, "namn": "Beef tallow"}]})
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        data = se_livsmedel.fetch_all(client)
    assert data["version"] is None and data["groups"] == {} and data["nutrients"] == {"1": []}


@pytest.mark.parametrize(("name", "group", "likely"), [
    ("Milk 3% fat fortified", "Drink", False),  # vitamins A and D
    ("Low-fat margarine 40% fat fortified", "Fat, oil", False),
    ("Oat drink 1.5% fat fortified", "Drink", True),
    ("Soyghurt plain fortified Ca vitD B12 folic acid riboflavin", "Dairy", True),
    ("Gruel for children powder oat unsweetened fortified", "Cereal, breakfast cereal, muesly", True),
    ("Meal replacement powder chocolate flavour", "Nutrient supply", True),
    ("Infant formula", "Miscellaneous", True),
    ("Oat gruel homemade", "Cereal, breakfast cereal, muesly", False),
])
def test_sweden_folic_acid_heuristic(name, group, likely):
    assert se_livsmedel._folic_acid_likely(name, group) is likely
