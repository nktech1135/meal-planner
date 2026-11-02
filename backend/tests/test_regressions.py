"""Bugs found in review, each pinned by the scenario that showed it."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Food
from app.services import exercise as svc
from app.sources.base import ExternalFood
from app.sources.registry import bulk_upsert_external_foods
from tests.conftest import register
from tests.test_api import create_food
from tests.test_exercise import gpx_file

NOW = datetime.now(UTC).isoformat()


@pytest.fixture
def c(user_client):
    user_client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "height_cm": 180, "weight_kg": 80,
                                          "timezone": "UTC"})
    return user_client


def test_editing_a_food_keeps_its_portions(c):
    bread = create_food(c, name="Bread", portions=[{"label": "slice", "gram_weight": 30}])
    create_food(c, name="Other", portions=[{"label": "cup", "gram_weight": 200}])  # so a new id would differ
    slice_id = bread["portions"][0]["id"]
    unit = f"portion:{slice_id}"
    entry = c.post("/api/log", json={"food_id": bread["id"], "quantity": 2, "unit": unit}).json()
    meal = c.post("/api/saved-meals", json={"name": "Toast", "items": [{"food_id": bread["id"], "quantity": 2,
                                                                       "unit": unit}]}).json()
    edited = c.put(f"/api/foods/{bread['id']}", json={
        "name": "Bread, wholemeal", "nutrients": {"energy_kcal": 250}, "portions": [
            {"id": slice_id, "label": "thick slice", "gram_weight": 40}, {"label": "loaf", "gram_weight": 800}]}).json()
    assert edited["portions"][0] == {"id": slice_id, "label": "thick slice", "gram_weight": 40}
    assert c.patch(f"/api/log/{entry['id']}", json={"quantity": 1}).status_code == 200
    assert c.post(f"/api/saved-meals/{meal['id']}/log", json={}).status_code == 201


def test_reimporting_keeps_portion_ids(c, db_session):
    def apple(grams):
        return ExternalFood(source="usda_fdc", source_id="1", name="Apple, raw", trust_level="analytical",
                            nutrients={"energy_kcal": (52.0, None)}, portions=[("1 medium", grams), ("1 cup", 125)])

    bulk_upsert_external_foods(db_session, [apple(180)])
    db_session.commit()
    food = db_session.query(Food).filter_by(source_id="1").one()
    before = {p.label: p.id for p in food.portions}
    bulk_upsert_external_foods(db_session, [apple(182)])
    db_session.commit()
    db_session.expire_all()
    food = db_session.get(Food, food.id)
    assert {p.label: p.id for p in food.portions} == before
    assert {p.label: p.gram_weight for p in food.portions}["1 medium"] == 182


def test_a_yield_in_use_cant_be_deleted(c):
    chicken = create_food(c, name="Chicken, raw")
    y = c.post("/api/yields", json={"raw_food_id": chicken["id"], "method": "roasted", "yield_factor": 0.75}).json()
    recipe = c.post("/api/recipes", json={"name": "Roast", "servings": 2, "ingredients": [
        {"food_id": chicken["id"], "grams": 300, "weighed_state": "cooked", "yield_id": y["id"]}]}).json()
    resp = c.delete(f"/api/yields/{y['id']}")
    assert resp.status_code == 409 and "1 recipe ingredient" in resp.json()["detail"]
    c.delete(f"/api/recipes/{recipe['id']}")
    assert c.delete(f"/api/yields/{y['id']}").status_code == 204


def test_times_with_an_offset_land_on_their_own_day(c):
    profile = c.get("/api/profile").json()
    c.put("/api/profile", json={**profile, "timezone": "Asia/Tokyo"})
    food = create_food(c)
    c.post("/api/log", json={"food_id": food["id"], "quantity": 100, "consumed_at": "2026-10-20T20:00:00+09:00"})
    assert len(c.get("/api/summary/day", params={"day": "2026-10-20"}).json()["entries"]) == 1
    c.post("/api/plan", json={"date": "2026-10-21", "meal": "dinner", "food_id": food["id"], "quantity": 100})
    assert c.post("/api/plan/log-day", json={"date": "2026-10-21"}).status_code == 201
    assert len(c.get("/api/summary/day", params={"day": "2026-10-21"}).json()["entries"]) == 1
    copied = c.post("/api/log/copy", json={"from_date": "2026-10-20", "to_date": "2026-10-22"})
    assert copied.status_code == 201
    assert len(c.get("/api/summary/day", params={"day": "2026-10-22"}).json()["entries"]) == 1


def test_null_in_an_edit_is_refused_not_a_crash(c):
    food = create_food(c)
    entry = c.post("/api/log", json={"food_id": food["id"], "quantity": 100}).json()
    for change in ({"quantity": None}, {"consumed_at": None}, {"meal": None}):
        assert c.patch(f"/api/log/{entry['id']}", json=change).status_code == 422
    assert c.get("/api/summary/day").json()["entries"][0]["consumed_at"] == entry["consumed_at"]
    item = c.post("/api/plan", json={"date": date.today().isoformat(), "food_id": food["id"], "quantity": 1}).json()
    assert c.patch(f"/api/plan/{item['id']}", json={"date": None}).status_code == 422
    assert c.patch(f"/api/plan/{item['id']}", json={"yield_id": None}).status_code == 200  # this one may be empty


def test_editing_a_note_keeps_what_was_logged(c):
    food = create_food(c, nutrients={"energy_kcal": 100})
    entry = c.post("/api/log", json={"food_id": food["id"], "quantity": 100}).json()
    c.put(f"/api/foods/{food['id']}", json={"name": food["name"], "nutrients": {"energy_kcal": 999}})
    noted = c.patch(f"/api/log/{entry['id']}", json={"note": "with salt", "meal": "dinner"}).json()
    assert noted["nutrients"]["energy_kcal"] == 100 and noted["note"] == "with salt"
    assert c.patch(f"/api/log/{entry['id']}", json={"quantity": 50}).json()["nutrients"]["energy_kcal"] == 499.5


def test_rest_days_are_judged_against_the_rest_day_target(c):
    today = datetime.now(UTC).date()
    base = next(r for r in c.get("/api/summary/day").json()["evaluation"] if r["code"] == "energy_kcal")["target"]
    fuel = create_food(c, name="Fuel", nutrients={"energy_kcal": 100})
    for day in (today - timedelta(days=1), today):
        c.post("/api/log", json={"food_id": fuel["id"], "quantity": base, "meal": "lunch",
                                 "consumed_at": datetime.combine(day, datetime.min.time(), UTC).replace(hour=12).isoformat()})
    c.post("/api/exercise", json={"date": (today - timedelta(days=1)).isoformat(), "name": "Ride", "duration_min": 60,
                                  "reported_kcal": 1080})
    trends = c.get("/api/trends", params={"days": 2, "end": today.isoformat()}).json()
    assert next(r for r in trends["evaluation"] if r["code"] == "energy_kcal")["days_ok"] == 1  # today, not yesterday


def test_shopping_ticks_last_the_week(c):
    food = create_food(c)
    monday = date(2026, 11, 2)
    sunday = monday + timedelta(days=6)
    c.post("/api/plan", json={"date": (monday + timedelta(days=3)).isoformat(), "food_id": food["id"], "quantity": 200})
    key = c.get("/api/plan/shopping", params={"start": monday.isoformat(), "end": sunday.isoformat()}).json()["items"][0]["key"]
    c.put("/api/plan/shopping/check", json={"start": monday.isoformat(), "end": sunday.isoformat(), "key": key,
                                            "checked": True})
    tuesday = (monday + timedelta(days=1)).isoformat()  # the next day this week's list starts a day later
    items = c.get("/api/plan/shopping", params={"start": tuesday, "end": sunday.isoformat()}).json()["items"]
    assert items[0]["checked"] is True
    c.put("/api/plan/shopping/check", json={"start": tuesday, "end": sunday.isoformat(), "key": key, "checked": False})
    items = c.get("/api/plan/shopping", params={"start": monday.isoformat(), "end": sunday.isoformat()}).json()["items"]
    assert items[0]["checked"] is False


@pytest.fixture
def hide(c, db_session):
    """Make a food someone else's, as if it was taken away from this user."""
    other = TestClient(app)
    stranger = register(other, "stranger@example.com")["id"]

    def hide(food_id: int) -> None:
        db_session.get(Food, food_id).owner_id = stranger
        db_session.commit()
    return hide


def test_shopping_list_says_what_it_left_out(c, hide):
    gone = create_food(c, name="Gone")
    day = date.today().isoformat()
    c.post("/api/plan", json={"date": day, "food_id": gone["id"], "quantity": 100})
    hide(gone["id"])
    shopping = c.get("/api/plan/shopping", params={"start": day, "end": day}).json()
    assert shopping["items"] == [] and shopping["skipped"] == ["Gone"]


def test_planning_a_saved_meal_is_all_or_nothing(c, hide):
    good, bad = create_food(c, name="Good"), create_food(c, name="Bad")
    meal = c.post("/api/saved-meals", json={"name": "Lunch", "items": [
        {"food_id": good["id"], "quantity": 100}, {"food_id": bad["id"], "quantity": 100}]}).json()
    hide(bad["id"])
    day = date.today().isoformat()
    assert c.post("/api/plan/from-saved-meal", json={"saved_meal_id": meal["id"], "date": day}).status_code == 404
    assert all(not d["items"] for d in c.get("/api/plan", params={"start": day, "end": day}).json())


def test_gpx_duration_leaves_out_pauses():
    start = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    walk = gpx_file(start).decode()
    # The same 30-minute walk, then an hour standing still at the end point, recorded every minute.
    still = "".join(f'<trkpt lat="{51.5 + 30 * 0.001}" lon="-0.12"><time>{(start + timedelta(minutes=31 + i)).isoformat()}'
                    f'</time></trkpt>' for i in range(60))
    [act] = svc.parse_gpx(walk.replace("</trkseg>", still + "</trkseg>").encode())
    assert act.duration_min == pytest.approx(30, abs=1)
    stationary = "".join(f'<trkpt lat="51.5" lon="-0.12"><time>{(start + timedelta(minutes=i)).isoformat()}</time></trkpt>'
                         for i in range(46))
    [gym] = svc.parse_gpx(f'<gpx><trk><trkseg>{stationary}</trkseg></trk></gpx>'.encode())
    assert gym.duration_min == 45  # hardly moving at all: the whole recording counts


def test_editing_an_imported_workout_keeps_the_device_figure(c, db_session):
    from app.models import Exercise

    today = datetime.now(UTC).date()
    ex = Exercise(user_id=1, date=today, name="Ride", source="fit", duration_min=60, reported_kcal=612.3456,
                  kcal=0, kcal_method="device", calc_note="", weight_kg=80)
    db_session.add(ex)
    db_session.commit()
    body = {"date": today.isoformat(), "name": "Evening ride", "duration_min": 60, "reported_kcal": 612.35}
    assert c.put(f"/api/exercise/{ex.id}", json=body).json()["kcal_method"] == "device"
    assert c.put(f"/api/exercise/{ex.id}", json=body | {"reported_kcal": 700}).json()["kcal_method"] == "entered"


def test_food_search_pages(c):
    for i in range(5):
        create_food(c, name=f"Mine {i}")
    first = c.get("/api/foods", params={"mine": True, "limit": 3}).json()
    rest = c.get("/api/foods", params={"mine": True, "limit": 3, "offset": 3}).json()
    assert [f["name"] for f in first + rest] == [f"Mine {i}" for i in range(5)]
