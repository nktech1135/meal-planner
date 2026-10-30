from datetime import UTC, datetime

import pytest

from app.services.forms import auto_resolve


@pytest.mark.parametrize("code,unit,names,expected", [
    ("vitamin_a_ug", "IU", ["Vitamin A", "Retinyl Palmitate"], 0.3),
    ("vitamin_a_ug", "IU", ["Vitamin A", "Beta-Carotene", "Vitamin A Acetate"], 0.3),  # same factor either way
    ("vitamin_a_ug", "mcg", ["Vitamin A", "Beta-Carotene", "Vitamin A Acetate"], None),  # 0.5 vs 1.0: ambiguous
    ("vitamin_a_ug", "IU", ["Vitamin A"], None),
    ("vitamin_e_mg", "IU", ["Vitamin E", "dl-alpha tocopheryl acetate"], 0.45),
    ("vitamin_e_mg", "IU", ["Vitamin E", "D-Alpha-Tocopheryl Acetate"], 0.67),
    ("folate_ug_dfe", "mcg", ["Folic Acid"], 1.7),
    ("folate_ug_dfe", "mcg", ["Folate", "Vitamin B9"], None),
])
def test_auto_resolve(code, unit, names, expected):
    opt = auto_resolve(code, unit, names)
    assert (opt.factor if opt else None) == expected


@pytest.fixture
def tagged_supplement(user_client, db_session):
    from app.models import Food, FoodNutrient

    food = Food(name="Imported multi", kind="supplement", basis="serving", serving_quantity=1, serving_unit="tablet",
                source="nih_dsld", source_id="x1", trust_level="label",
                nutrients=[FoodNutrient(nutrient_code="vitamin_c_mg", amount=60)],
                other_components=[{"name": "Vitamin A", "amount": 5000, "unit": "IU", "nutrient_code": "vitamin_a_ug",
                                   "reason": "form", "note": "not converted"}])
    db_session.add(food)
    db_session.commit()
    user_client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "timezone": "UTC"})
    return user_client, food.id


def test_partial_status_then_choice(tagged_supplement):
    client, food_id = tagged_supplement
    client.post("/api/log", json={"food_id": food_id, "quantity": 1, "unit": "serving", "meal": "supplement",
                                  "consumed_at": datetime.now(UTC).isoformat()})
    day = client.get("/api/summary/day").json()
    vit_a = next(r for r in day["evaluation"] if r["code"] == "vitamin_a_ug")
    assert vit_a["status"] == "partial" and vit_a["uncounted"][0]["amount"] == 5000

    forms = client.get(f"/api/foods/{food_id}/forms").json()
    assert [o["key"] for o in forms[0]["options"]] == ["retinol", "beta_carotene_supplement", "carotenoids_food"]
    resp = client.put(f"/api/foods/{food_id}/forms", json={"component_name": "Vitamin A", "option_key": "retinol"}).json()
    assert resp["recalculated_entries"] == 1 and resp["forms"][0]["chosen"] == "retinol"

    day = client.get("/api/summary/day").json()
    assert day["totals"]["vitamin_a_ug"] == pytest.approx(1500)
    entry = day["entries"][0]
    assert entry["trust_level"] == "user"  # the form was the user's choice
    assert any("your choice" in n for n in entry["calc_notes"])
    vit_a = next(r for r in day["evaluation"] if r["code"] == "vitamin_a_ug")
    assert vit_a["uncounted"] == [] and vit_a["status"] != "partial"

    bad = client.put(f"/api/foods/{food_id}/forms", json={"component_name": "Vitamin A", "option_key": "nope"})
    assert bad.status_code == 422
    client.put(f"/api/foods/{food_id}/forms", json={"component_name": "Vitamin A", "option_key": None})
    assert "vitamin_a_ug" not in client.get("/api/summary/day").json()["totals"]


def test_pinned_nutrients(user_client):
    assert user_client.put("/api/profile", json={"pinned_nutrients": ["iron_mg", "iron_mg", "vitamin_d_ug"]}).json()[
        "pinned_nutrients"] == ["iron_mg", "vitamin_d_ug"]
    assert user_client.put("/api/profile", json={"pinned_nutrients": ["nope"]}).status_code == 422


def test_manual_component_can_be_form_dependent(user_client):
    food = user_client.post("/api/foods", json={"name": "My multi", "kind": "supplement", "basis": "serving",
                                                "serving_quantity": 1, "serving_unit": "tablet", "other_components": [
                                                    {"name": "Vitamin A", "amount": 3000, "unit": "IU",
                                                     "nutrient_code": "vitamin_a_ug"}]}).json()
    forms = user_client.get(f"/api/foods/{food['id']}/forms").json()
    assert forms[0]["nutrient_code"] == "vitamin_a_ug" and len(forms[0]["options"]) == 3
    bad = user_client.post("/api/foods", json={"name": "x", "other_components": [
        {"name": "A", "amount": 1, "unit": "IU", "nutrient_code": "nope"}]})
    assert bad.status_code == 422
