from datetime import UTC, date, datetime, timedelta

import pytest

from tests.test_api import create_food

TODAY = datetime.now(UTC).date()
YESTERDAY = TODAY - timedelta(days=1)


def at(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC).isoformat()


def log(client, **body):
    resp = client.post("/api/log", json={"meal": "breakfast"} | body)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def setup(user_client):
    user_client.put("/api/profile", json={"timezone": "UTC"})
    oats = create_food(user_client, name="Oats", nutrients={"energy_kcal": 380, "protein_g": 13})
    milk = create_food(user_client, name="Milk", nutrients={"energy_kcal": 60, "protein_g": 3.3})
    return user_client, oats, milk


def test_edit_entry_recalculates(setup):
    client, oats, _ = setup
    entry = log(client, food_id=oats["id"], quantity=50, consumed_at=at(TODAY, 8))
    edited = client.patch(f"/api/log/{entry['id']}", json={"quantity": 80, "meal": "snack", "note": "bigger bowl"}).json()
    assert edited["nutrients"]["energy_kcal"] == pytest.approx(304)
    assert edited["meal"] == "snack" and edited["note"] == "bigger bowl"
    assert edited["consumed_at"].startswith(TODAY.isoformat())
    bad = client.patch(f"/api/log/{entry['id']}", json={"unit": "serving"})  # no serving size
    assert bad.status_code == 422
    assert client.get("/api/summary/day", params={"day": TODAY.isoformat()}).json()["totals"]["energy_kcal"] == pytest.approx(304)


def test_edit_after_food_deleted_only_allows_metadata(setup):
    client, _, milk = setup
    entry = log(client, food_id=milk["id"], quantity=200, consumed_at=at(TODAY, 8))
    assert client.delete(f"/api/foods/{milk['id']}").status_code == 204
    assert client.patch(f"/api/log/{entry['id']}", json={"note": "ok"}).json()["note"] == "ok"
    assert client.patch(f"/api/log/{entry['id']}", json={"quantity": 1}).status_code == 409


def test_copy_meal_and_day(setup):
    client, oats, milk = setup
    log(client, food_id=oats["id"], quantity=50, consumed_at=at(YESTERDAY, 7))
    log(client, food_id=milk["id"], quantity=200, consumed_at=at(YESTERDAY, 7))
    log(client, food_id=oats["id"], quantity=30, meal="snack", consumed_at=at(YESTERDAY, 15))
    copied = client.post("/api/log/copy", json={"from_date": YESTERDAY.isoformat(), "to_date": TODAY.isoformat(),
                                                "meal": "breakfast"}).json()
    assert len(copied) == 2 and all(e["consumed_at"].startswith(TODAY.isoformat() + "T07:00") for e in copied)
    whole = client.post("/api/log/copy", json={"from_date": YESTERDAY.isoformat(), "to_date": TODAY.isoformat()})
    assert len(whole.json()) == 3
    empty = client.post("/api/log/copy", json={"from_date": "2000-01-01", "to_date": TODAY.isoformat()})
    assert empty.status_code == 404


def test_suggestions_rank_by_meal_then_frequency(setup):
    client, oats, milk = setup
    for _ in range(3):
        log(client, food_id=milk["id"], quantity=150, meal="snack")
    log(client, food_id=oats["id"], quantity=60, meal="breakfast")
    breakfast = client.get("/api/log/suggestions", params={"meal": "breakfast"}).json()
    assert [s["label"] for s in breakfast] == ["Oats", "Milk"]
    assert breakfast[0]["quantity"] == 60 and breakfast[0]["energy_kcal"] == pytest.approx(228)
    overall = client.get("/api/log/suggestions").json()
    assert overall[0]["label"] == "Milk" and overall[0]["times"] == 3
    assert [s["label"] for s in client.get("/api/log/suggestions", params={"q": "oat"}).json()] == ["Oats"]


def test_saved_meals(setup):
    client, oats, milk = setup
    meal = client.post("/api/saved-meals", json={"name": "Usual breakfast", "default_meal": "breakfast", "items": [
        {"food_id": oats["id"], "quantity": 50}, {"food_id": milk["id"], "quantity": 200}]}).json()
    assert [i["label"] for i in meal["items"]] == ["Oats", "Milk"]
    entries = client.post(f"/api/saved-meals/{meal['id']}/log", json={}).json()
    assert {e["meal"] for e in entries} == {"breakfast"}
    assert sum(e["nutrients"]["energy_kcal"] for e in entries) == pytest.approx(190 + 120)
    bad = client.post("/api/saved-meals", json={"name": "x", "items": [{"food_id": 99999, "quantity": 1}]})
    assert bad.status_code == 404
    from_log = client.post("/api/saved-meals/from-log", json={"name": "Copy", "date": TODAY.isoformat(),
                                                              "meal": "breakfast"}).json()
    assert len(from_log["items"]) == 2
    assert client.delete(f"/api/saved-meals/{meal['id']}").status_code == 204
    assert [m["name"] for m in client.get("/api/saved-meals").json()] == ["Copy"]
