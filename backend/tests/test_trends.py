from datetime import UTC, datetime, timedelta

import pytest

from tests.test_api import create_food

TODAY = datetime.now(UTC).date()


def log_day(client, food_id, day, grams):
    resp = client.post("/api/log", json={"food_id": food_id, "quantity": grams, "meal": "lunch",
                                         "consumed_at": datetime(day.year, day.month, day.day, 12, tzinfo=UTC).isoformat()})
    assert resp.status_code == 201, resp.text


@pytest.fixture
def client(user_client):
    user_client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "height_cm": 180, "weight_kg": 80,
                                          "timezone": "UTC"})
    return user_client


def test_body_measurements_sync_profile_weight(client):
    assert client.put(f"/api/body/{TODAY}", json={}).status_code == 422
    assert client.put(f"/api/body/{TODAY + timedelta(days=1)}", json={"weight_kg": 80}).status_code == 422
    client.put(f"/api/body/{TODAY - timedelta(days=3)}", json={"weight_kg": 81.0})
    client.put(f"/api/body/{TODAY}", json={"weight_kg": 79.5, "waist_cm": 88, "note": "morning"})
    assert client.get("/api/profile").json()["weight_kg"] == 79.5
    client.put(f"/api/body/{TODAY}", json={"weight_kg": 79.0})  # same day: replaced, not duplicated
    rows = client.get("/api/body").json()
    assert [r["weight_kg"] for r in rows] == [81.0, 79.0]
    assert rows[1]["waist_cm"] is None
    client.delete(f"/api/body/{TODAY}")
    assert client.get("/api/profile").json()["weight_kg"] == 81.0


def test_trends_average_logged_days_only(client):
    food = create_food(client, name="Lentils", nutrients={"energy_kcal": 100, "protein_g": 9, "iron_mg": 3})
    for i in (0, 2, 4):  # 3 logged days in a 7-day window
        log_day(client, food["id"], TODAY - timedelta(days=i), 2000)
    t = client.get("/api/trends", params={"days": 7}).json()
    assert t["logged_days"] == 3 and len(t["daily"]) == 7
    assert t["averages"]["energy_kcal"] == pytest.approx(2000)  # not diluted by unlogged days
    iron = next(r for r in t["evaluation"] if r["code"] == "iron_mg")
    assert iron["amount"] == pytest.approx(60) and iron["days_ok"] == 0  # 60 mg/day exceeds the 45 mg UL
    protein = next(r for r in t["evaluation"] if r["code"] == "protein_g")
    assert protein["days_ok"] == 3


def test_energy_estimate(client):
    food = create_food(client, name="Food", nutrients={"energy_kcal": 100})
    t = client.get("/api/trends", params={"days": 30}).json()
    assert t["energy_estimate"]["available"] is False
    # 21 days eating 2,500 kcal while losing 0.05 kg/day
    for i in range(21):
        day = TODAY - timedelta(days=20 - i)
        log_day(client, food["id"], day, 2500)
        client.put(f"/api/body/{day}", json={"weight_kg": 80 - 0.05 * i})
    est = client.get("/api/trends", params={"days": 30}).json()["energy_estimate"]
    assert est["available"] is True and est["days"] == 20 and est["average_intake_kcal"] == 2500
    assert est["trend_change_kg"] < 0  # smoothed trend lags the scale but points down
    assert est["maintenance_kcal"] > 2500  # losing weight means maintenance is above intake


def test_estimate_needs_enough_logging(client):
    food = create_food(client, name="Food", nutrients={"energy_kcal": 100})
    for i in range(21):
        day = TODAY - timedelta(days=20 - i)
        client.put(f"/api/body/{day}", json={"weight_kg": 80})
        if i % 3 == 0:
            log_day(client, food["id"], day, 2500)
    est = client.get("/api/trends", params={"days": 30}).json()["energy_estimate"]
    assert est["available"] is False and "logged on" in est["reason"]


def test_unit_system_preference(client):
    assert client.put("/api/profile", json={"unit_system": "imperial", "timezone": "UTC"}).json()["unit_system"] == "imperial"
    assert client.put("/api/profile", json={"unit_system": "furlongs"}).status_code == 422
