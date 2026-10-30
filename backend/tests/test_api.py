from datetime import UTC, datetime

import pytest

from app.main import app
from app.nutrients import Trust
from app.routers.sources import get_sources
from app.sources.base import DataSource, ExternalFood, SearchHit
from tests.conftest import register

NOW = datetime.now(UTC).isoformat()


def create_food(client, **overrides):
    body = {"name": "Chicken breast", "state": "raw", "nutrients": {"energy_kcal": 120, "protein_g": 22.5},
            "citation": "package label"} | overrides
    resp = client.post("/api/foods", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def log(client, **body):
    resp = client.post("/api/log", json={"consumed_at": NOW, "meal": "lunch"} | body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_auth_flow(client):
    assert client.get("/api/auth/me").status_code == 401
    first = register(client)
    assert first["is_admin"] is True
    assert client.get("/api/auth/me").json()["email"] == "a@example.com"
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "A@example.com", "password": "correct horse battery"})
    assert ok.status_code == 200
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "x" * 12}).status_code == 409
    second = register(client, "b@example.com")
    assert second["is_admin"] is False


def test_private_foods_are_isolated(client):
    register(client, "a@example.com")
    food = create_food(client)
    assert food["trust_level"] == "user"
    client.cookies.clear()
    register(client, "b@example.com")
    assert client.get(f"/api/foods/{food['id']}").status_code == 404
    assert client.get("/api/foods", params={"q": "chicken"}).json() == []
    assert client.post("/api/log", json={"food_id": food["id"], "quantity": 100}).status_code == 404


def test_log_and_day_summary(user_client):
    client = user_client
    client.put("/api/profile", json={"sex": "male", "birth_date": "1990-01-01", "height_cm": 180, "weight_kg": 80,
                                     "timezone": "UTC"})
    food = create_food(client)
    entry = log(client, food_id=food["id"], quantity=200, unit="g")
    assert entry["nutrients"]["protein_g"] == pytest.approx(45)
    summary = client.get("/api/summary/day").json()
    assert summary["totals"]["energy_kcal"] == pytest.approx(240)
    assert summary["energy_by_trust"] == {"user": 240}
    protein = next(r for r in summary["evaluation"] if r["code"] == "protein_g")
    assert protein["min"] == 64 and protein["status"] == "below"
    client.delete(f"/api/log/{entry['id']}")
    assert client.get("/api/summary/day").json()["totals"] == {}


def test_cooked_weight_logging_through_measured_yield(user_client):
    client = user_client
    food = create_food(client)
    y = client.post("/api/yields", json={"raw_food_id": food["id"], "method": "roasted", "raw_weight_g": 500,
                                         "cooked_weight_g": 375}).json()
    assert y["yield_factor"] == pytest.approx(0.75)
    assert y["trust_level"] == "user"
    assert client.get(f"/api/foods/{food['id']}/yields").json()[0]["id"] == y["id"]
    missing = client.post("/api/log", json={"food_id": food["id"], "quantity": 150, "weighed_state": "cooked"})
    assert missing.status_code == 422
    entry = log(client, food_id=food["id"], quantity=150, weighed_state="cooked", yield_id=y["id"])
    assert entry["grams"] == pytest.approx(200)
    assert entry["nutrients"]["energy_kcal"] == pytest.approx(240)
    assert any("assumed fully retained" in n for n in entry["calc_notes"])


def test_published_yield_requires_citation(user_client):
    food = create_food(user_client)
    resp = user_client.post("/api/yields", json={"raw_food_id": food["id"], "method": "boiled", "yield_factor": 2.4,
                                                 "basis": "published"})
    assert resp.status_code == 422


def test_recipe_and_logging_by_serving(user_client):
    client = user_client
    rice = create_food(client, name="Rice, dry", nutrients={"energy_kcal": 360, "protein_g": 7})
    recipe = client.post("/api/recipes", json={"name": "Rice", "servings": 4, "cooked_weight_g": 750,
                                               "ingredients": [{"food_id": rice["id"], "grams": 300}]}).json()
    assert recipe["nutrition"]["per_serving"]["energy_kcal"] == pytest.approx(270)
    assert recipe["ingredients"][0]["food_name"] == "Rice, dry"
    entry = log(client, recipe_id=recipe["id"], quantity=1, unit="serving")
    assert entry["nutrients"]["energy_kcal"] == pytest.approx(270)
    assert entry["grams"] == pytest.approx(187.5)
    # Snapshot: editing the recipe later doesn't rewrite the logged entry.
    client.put(f"/api/recipes/{recipe['id']}", json={"name": "Rice", "servings": 2, "cooked_weight_g": 750,
                                                      "ingredients": [{"food_id": rice["id"], "grams": 300}]})
    day = client.get("/api/summary/day").json()
    assert day["entries"][0]["nutrients"]["energy_kcal"] == pytest.approx(270)
    # Ingredient in use can't be deleted out from under the recipe.
    assert client.delete(f"/api/foods/{rice['id']}").status_code == 409


def test_supplement_upper_limit_uses_supplement_intake_only(user_client):
    client = user_client
    client.put("/api/profile", json={"sex": "female", "birth_date": "1985-01-01", "timezone": "UTC"})
    spinach = create_food(client, name="Spinach", nutrients={"magnesium_mg": 79})
    supp = create_food(client, name="Magnesium glycinate", kind="supplement", basis="serving", serving_quantity=2,
                       serving_unit="capsule", nutrients={"magnesium_mg": 400})
    log(client, food_id=spinach["id"], quantity=500)  # 395 mg from food: no UL issue
    day = client.get("/api/summary/day").json()
    assert day["alerts"] == []
    log(client, food_id=supp["id"], quantity=1, unit="serving", meal="supplement")
    day = client.get("/api/summary/day").json()
    mg = next(r for r in day["evaluation"] if r["code"] == "magnesium_mg")
    assert mg["amount"] == pytest.approx(795)
    assert mg["limit_amount"] == pytest.approx(400)
    assert mg["status"] == "above_max"
    assert day["alerts"] and "supplements" in day["alerts"][0]


def test_imported_foods_are_read_only_but_copyable(user_client):
    class FakeSource(DataSource):
        key, name, description, homepage, trust_level = "fake", "Fake", "", "", Trust.ANALYTICAL
        enabled = True

        def search(self, query, limit=20):
            return [SearchHit("fake", "1", "Oats, raw", None, "food", "analytical")]

        def fetch(self, source_id, name_hint=None):
            return ExternalFood("fake", source_id, "Oats, raw", "analytical", state="raw",
                                nutrients={"energy_kcal": (379.0, "Analytical")}, portions=[("1 cup", 81.0)])

    app.dependency_overrides[get_sources] = lambda: {"fake": FakeSource(None, None)}
    client = user_client
    hits = client.get("/api/sources/fake/search", params={"q": "oats"}).json()
    assert hits[0]["imported_food_id"] is None
    food = client.post("/api/sources/fake/import", json={"source_id": "1"}).json()
    assert food["owner_id"] is None and food["trust_level"] == "analytical"
    assert client.get("/api/sources/fake/search", params={"q": "oats"}).json()[0]["imported_food_id"] == food["id"]
    edit = client.put(f"/api/foods/{food['id']}", json={"name": "x", "nutrients": {}})
    assert edit.status_code == 403
    copy = client.post(f"/api/foods/{food['id']}/copy").json()
    assert copy["trust_level"] == "user" and copy["owner_id"] is not None
    portion_id = food["portions"][0]["id"]
    entry = log(client, food_id=food["id"], quantity=1, unit=f"portion:{portion_id}")
    assert entry["nutrients"]["energy_kcal"] == pytest.approx(379 * 0.81)


def test_disabled_source_is_refused(user_client):
    sources = user_client.get("/api/sources").json()
    off = next(s for s in sources if s["key"] == "open_food_facts")
    assert off["enabled"] is False and off["trust_level"] == "unverified"
    assert user_client.get("/api/sources/open_food_facts/search", params={"q": "oats"}).status_code == 403


def test_validation(user_client):
    bad = user_client.post("/api/foods", json={"name": "x", "nutrients": {"not_a_nutrient": 1}})
    assert bad.status_code == 422
    assert user_client.put("/api/profile", json={"timezone": "Mars/Base"}).status_code == 422
    naive = user_client.post("/api/log", json={"food_id": 1, "quantity": 1, "consumed_at": "2026-01-01T12:00:00"})
    assert naive.status_code in (404, 422)


def test_derived_yield_is_computed_server_side(user_client):
    raw = create_food(user_client, nutrients={"protein_g": 22.5, "water_g": 74})
    cooked = create_food(user_client, name="Chicken breast, roasted", state="cooked",
                         nutrients={"protein_g": 31.0, "water_g": 65})
    y = user_client.post("/api/yields", json={"raw_food_id": raw["id"], "cooked_food_id": cooked["id"],
                                              "method": "roasted", "basis": "derived", "yield_factor": 0.99}).json()
    assert y["yield_factor"] == pytest.approx(22.5 / 31.0, abs=1e-4)  # client value ignored
    assert y["basis"] == "derived"


def test_advisor_without_api_key_is_503(user_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    resp = user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert resp.status_code == 503 and "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_timezone_unset_until_chosen(user_client):
    assert user_client.get("/api/profile").json()["timezone"] is None
    assert user_client.get("/api/summary/day").status_code == 200
    assert user_client.put("/api/profile", json={"timezone": "UTC"}).json()["timezone"] == "UTC"
