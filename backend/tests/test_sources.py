import httpx
import pytest
import respx

from app.config import Settings
from app.sources.base import SourceError, guess_state
from app.sources.registry import build_sources, upsert_external_food
from tests.conftest import load_fixture


@pytest.fixture
def settings():
    return Settings(usda_fdc_api_key="TESTKEY", nutritionix_app_id="id", nutritionix_app_key="key",
                    edamam_app_id="id", edamam_app_key="key", _env_file=None)


@pytest.fixture
def sources(settings):
    with httpx.Client() as client:
        yield build_sources(settings, client)


@respx.mock
def test_fdc_foundation_food(sources):
    respx.get("https://api.nal.usda.gov/fdc/v1/food/2646170").respond(json=load_fixture("fdc_food_2646170.json"))
    food = sources["usda_fdc"].fetch("2646170")
    assert food.name == "Chicken, breast, boneless, skinless, raw"
    assert food.state == "raw"
    assert food.trust_level == "analytical"
    # Foundation foods have no 208 energy; Atwater-specific (958) is preferred over general (957).
    assert food.nutrients["energy_kcal"][0] == pytest.approx(112.20227)
    assert food.nutrients["protein_g"][0] == pytest.approx(22.525)
    assert food.nutrients["sodium_mg"][0] == pytest.approx(65.75)
    assert food.citation.startswith("U.S. Department of Agriculture")
    assert food.source_url.endswith("/2646170/nutrients")


@respx.mock
def test_fdc_search(sources):
    route = respx.get("https://api.nal.usda.gov/fdc/v1/foods/search").respond(json=load_fixture("fdc_search.json"))
    hits = sources["usda_fdc"].search("chicken breast raw", 2)
    assert route.calls.last.request.url.params["api_key"] == "TESTKEY"
    assert hits[0].source_id == "2646170"
    assert hits[0].trust_level == "analytical"
    assert "protein_g" in hits[0].summary


@respx.mock
def test_dsld_label(sources):
    respx.get("https://api.ods.od.nih.gov/dsld/v9/label/1225").respond(json=load_fixture("dsld_label_1225.json"))
    supp = sources["nih_dsld"].fetch("1225")
    assert supp.kind == "supplement" and supp.basis == "serving"
    assert (supp.serving_quantity, supp.serving_unit) == (2, "Softgel(s)")
    assert supp.trust_level == "label"
    assert supp.nutrients["vitamin_d_ug"][0] == pytest.approx(25)  # 1000 IU
    assert supp.nutrients["calcium_mg"][0] == 1200
    assert supp.nutrients["energy_kcal"][0] == 15
    assert "off-market" in supp.citation


@respx.mock
def test_dsld_search(sources):
    respx.get("https://api.ods.od.nih.gov/dsld/v9/search-filter").respond(json=load_fixture("dsld_search.json"))
    hits = sources["nih_dsld"].search("vitamin d3", 2)
    assert hits and all(h.kind == "supplement" and h.trust_level == "label" for h in hits)


def test_dsld_ambiguous_units_are_not_guessed():
    from app.sources.nih_dsld import parse_label

    label = {"ingredientRows": [
        {"name": "Vitamin A", "ingredientGroup": "Vitamin A",
         "quantity": [{"servingSizeOrder": 1, "quantity": 5000, "unit": "IU", "operator": "="}]},
        {"name": "Folate", "ingredientGroup": "Folate",
         "quantity": [{"servingSizeOrder": 1, "quantity": 680, "unit": "mcg DFE", "operator": "="}]},
        {"name": "Ashwagandha", "ingredientGroup": "Ashwagandha",
         "quantity": [{"servingSizeOrder": 1, "quantity": 300, "unit": "mg", "operator": "="}]},
    ]}
    nutrients, others, _ = parse_label(label)
    assert "vitamin_a_ug" not in nutrients
    assert nutrients["folate_ug_dfe"][0] == 680
    names = {o["name"]: o for o in others}
    assert "ambiguous" in names["Vitamin A"]["note"]
    assert names["Ashwagandha"]["amount"] == 300


@respx.mock
def test_nutritionix_branded_converted_to_per_100g(sources):
    respx.get("https://trackapi.nutritionix.com/v2/search/item").respond(json={"foods": [{
        "food_name": "Protein Bar", "brand_name": "Acme", "serving_qty": 1, "serving_unit": "bar",
        "serving_weight_grams": 60,
        "full_nutrients": [{"attr_id": 208, "value": 240}, {"attr_id": 203, "value": 20}, {"attr_id": 307, "value": 150}],
    }]})
    food = sources["nutritionix"].fetch("branded:abc123")
    assert food.trust_level == "commercial"
    assert food.basis == "100g"
    assert food.nutrients["energy_kcal"][0] == pytest.approx(400)
    assert food.nutrients["sodium_mg"][0] == pytest.approx(250)
    assert food.portions == [("1 bar", 60.0)]


@respx.mock
def test_edamam_nutrients(sources):
    respx.post("https://api.edamam.com/api/food-database/v2/nutrients").respond(json={
        "totalNutrients": {"ENERC_KCAL": {"quantity": 52, "unit": "kcal"}, "PROCNT": {"quantity": 0.26, "unit": "g"},
                           "VITC": {"quantity": 4.6, "unit": "mg"}},
        "ingredients": [{"parsed": [{"food": "apple", "foodId": "food_x", "weight": 100}]}],
    })
    food = sources["edamam"].fetch("food_x")
    assert food.name == "apple" and food.trust_level == "commercial"
    assert food.nutrients["vitamin_c_mg"][0] == pytest.approx(4.6)


def test_unverified_source_disabled_by_default(sources):
    off = sources["open_food_facts"]
    assert not off.enabled
    assert "ENABLE_UNVERIFIED_SOURCES" in off.disabled_reason


@respx.mock
def test_open_food_facts_flagged_unverified():
    settings = Settings(enable_unverified_sources=True, _env_file=None)
    respx.get("https://world.openfoodfacts.org/api/v2/product/123").respond(json={"product": {
        "product_name": "Oats", "brands": "X", "serving_quantity": "40",
        "nutriments": {"energy-kcal_100g": 370, "proteins_100g": 13, "sodium_100g": 0.006},
    }})
    with httpx.Client() as client:
        food = build_sources(settings, client)["open_food_facts"].fetch("123")
    assert food.trust_level == "unverified"
    assert food.nutrients["sodium_mg"][0] == pytest.approx(6)
    assert food.serving_size_g == 40


@respx.mock
def test_upstream_errors_become_source_errors(sources):
    respx.get("https://api.nal.usda.gov/fdc/v1/food/1").respond(status_code=429)
    with pytest.raises(SourceError, match="rate limited"):
        sources["usda_fdc"].fetch("1")


@respx.mock
def test_reimport_replaces_nutrients(sources, db_session):
    payload = load_fixture("fdc_food_2646170.json")
    respx.get("https://api.nal.usda.gov/fdc/v1/food/2646170").respond(json=payload)
    first = upsert_external_food(db_session, sources["usda_fdc"].fetch("2646170"))
    second = upsert_external_food(db_session, sources["usda_fdc"].fetch("2646170"))
    assert first.id == second.id
    assert second.owner_id is None
    assert len({n.nutrient_code for n in second.nutrients}) == len(second.nutrients)


@pytest.mark.parametrize("text,expected", [
    ("Chicken, breast, boneless, skinless, raw", ("raw", None)),
    ("Chicken, broilers or fryers, breast, meat only, cooked, roasted", ("cooked", "roasted")),
    ("Rice, white, long-grain, regular, enriched, cooked", ("cooked", None)),
    ("Butter, salted", (None, None)),
])
def test_guess_state(text, expected):
    assert guess_state(text) == expected
