from datetime import UTC, datetime, timedelta

import pytest

from tests.test_api import create_food

TODAY = datetime.now(UTC).date()
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture
def setup(user_client):
    c = user_client
    c.put("/api/profile", json={"sex": "female", "birth_date": "1990-01-01", "height_cm": 165, "weight_kg": 60,
                                "timezone": "UTC"})
    rice = create_food(c, name="Rice, dry", nutrients={"energy_kcal": 360, "protein_g": 7})
    chicken = create_food(c, name="Chicken, raw", state="raw", nutrients={"energy_kcal": 120, "protein_g": 22.5})
    y = c.post("/api/yields", json={"raw_food_id": chicken["id"], "method": "roasted", "yield_factor": 0.75}).json()
    recipe = c.post("/api/recipes", json={"name": "Rice bowl", "servings": 4, "cooked_weight_g": 1000, "ingredients": [
        {"food_id": rice["id"], "grams": 400}, {"food_id": chicken["id"], "grams": 600}]}).json()
    vit = create_food(c, name="Vitamin D", kind="supplement", basis="serving", serving_quantity=1, serving_unit="softgel",
                      nutrients={"vitamin_d_ug": 25})
    return c, rice, chicken, y, recipe, vit


def test_plan_projection_and_logging(setup):
    c, rice, chicken, y, recipe, vit = setup
    a = c.post("/api/plan", json={"date": TOMORROW.isoformat(), "meal": "lunch", "recipe_id": recipe["id"],
                                  "quantity": 1, "unit": "serving"}).json()
    b = c.post("/api/plan", json={"date": TOMORROW.isoformat(), "meal": "dinner", "food_id": chicken["id"],
                                  "quantity": 150, "weighed_state": "cooked", "yield_id": y["id"]}).json()
    c.post("/api/plan", json={"date": TOMORROW.isoformat(), "meal": "supplement", "food_id": vit["id"],
                              "quantity": 1, "unit": "serving"})
    assert c.post("/api/plan", json={"date": TOMORROW.isoformat(), "food_id": 999, "quantity": 1}).status_code == 404
    days = c.get("/api/plan", params={"start": TODAY.isoformat(), "end": TOMORROW.isoformat()}).json()
    assert days[0]["items"] == [] and len(days[1]["items"]) == 3
    assert days[1]["totals"]["energy_kcal"] == pytest.approx((1440 + 720) / 4 + 240)
    assert next(r for r in days[1]["evaluation"] if r["code"] == "protein_g")["amount"] == pytest.approx(
        (28 + 135) / 4 + 45)
    assert c.get("/api/plan", params={"start": TODAY.isoformat(), "end": (TODAY + timedelta(days=90)).isoformat()}
                 ).status_code == 422

    entry = c.post(f"/api/plan/{a['id']}/log").json()
    assert entry["meal"] == "lunch" and entry["consumed_at"].startswith(TOMORROW.isoformat() + "T12:30")
    assert c.post(f"/api/plan/{a['id']}/log").status_code == 409
    logged = c.post("/api/plan/log-day", json={"date": TOMORROW.isoformat()}).json()
    assert len(logged) == 2  # the remaining two items
    assert c.post("/api/plan/log-day", json={"date": TOMORROW.isoformat()}).json() == []

    edited = c.patch(f"/api/plan/{b['id']}", json={"quantity": 300}).json()
    assert edited["nutrients"]["energy_kcal"] == pytest.approx(480)
    assert c.patch(f"/api/plan/{b['id']}", json={"unit": "serving"}).status_code == 422


def test_copy_and_saved_meal(setup):
    c, rice, *_ = setup
    c.post("/api/plan", json={"date": TODAY.isoformat(), "food_id": rice["id"], "quantity": 80})
    assert c.post("/api/plan/copy", json={"from_start": TODAY.isoformat(), "from_end": TODAY.isoformat(),
                                          "to_start": TOMORROW.isoformat()}).json() == {"copied": 1}
    meal = c.post("/api/saved-meals", json={"name": "Rice", "default_meal": "lunch",
                                            "items": [{"food_id": rice["id"], "quantity": 50}]}).json()
    added = c.post("/api/plan/from-saved-meal", json={"saved_meal_id": meal["id"], "date": TOMORROW.isoformat()}).json()
    assert added[0]["origin"] == "saved_meal" and added[0]["meal"] == "lunch"
    day = c.get("/api/plan", params={"start": TOMORROW.isoformat(), "end": TOMORROW.isoformat()}).json()[0]
    assert sorted(i["origin"] for i in day["items"]) == ["copy", "saved_meal"]
    # origin can't be set by the client
    item = c.post("/api/plan?origin=advisor", json={"date": TODAY.isoformat(), "food_id": rice["id"], "quantity": 1}).json()
    assert item["origin"] == "manual"


def test_shopping_list(setup):
    c, rice, chicken, y, recipe, vit = setup
    for d in (TODAY, TOMORROW):
        c.post("/api/plan", json={"date": d.isoformat(), "recipe_id": recipe["id"], "quantity": 2, "unit": "serving"})
    c.post("/api/plan", json={"date": TOMORROW.isoformat(), "food_id": chicken["id"], "quantity": 150,
                              "weighed_state": "cooked", "yield_id": y["id"]})
    c.post("/api/plan", json={"date": TOMORROW.isoformat(), "food_id": vit["id"], "quantity": 1, "unit": "serving"})
    params = {"start": TODAY.isoformat(), "end": TOMORROW.isoformat()}
    items = {i["name"]: i for i in c.get("/api/plan/shopping", params=params).json()["items"]}
    assert items["Rice, dry"]["amount"] == pytest.approx(400)  # 2 × half the recipe
    assert items["Chicken, raw"]["amount"] == pytest.approx(600 + 200)  # recipe + 150 g cooked → 200 g raw
    assert items["Chicken, raw"]["used_for"] == ["Chicken, raw", "Rice bowl"]
    assert items["Vitamin D"]["unit"].startswith("servings") and items["Vitamin D"]["amount"] == 1
    key = items["Rice, dry"]["key"]
    c.put("/api/plan/shopping/check", json={**params, "key": key, "checked": True})
    assert {i["name"]: i for i in c.get("/api/plan/shopping", params=params).json()["items"]}["Rice, dry"]["checked"]
    c.put("/api/plan/shopping/check", json={**params, "key": key, "checked": False})
    assert not {i["name"]: i for i in c.get("/api/plan/shopping", params=params).json()["items"]}["Rice, dry"]["checked"]
