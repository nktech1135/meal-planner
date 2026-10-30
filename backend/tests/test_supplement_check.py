from datetime import UTC, datetime, time, timedelta

import pytest

from tests.conftest import register

PROFILE = {"sex": "male", "birth_date": "1985-01-01", "height_cm": 180, "weight_kg": 80, "activity_level": "moderate",
           "goal": "maintain", "timezone": "UTC"}


def _food(client, name, nutrients, **extra):
    body = {"name": name, "nutrients": nutrients, **extra}
    if extra.get("kind") == "supplement":
        body.setdefault("basis", "serving")
        body.setdefault("serving_quantity", 1)
        body.setdefault("serving_unit", "tablet")
    resp = client.post("/api/foods", json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _log(client, food_id, days_ago, quantity, unit, meal="lunch"):
    when = datetime.combine(datetime.now(UTC).date() - timedelta(days=days_ago), time(12), tzinfo=UTC)
    resp = client.post("/api/log", json={"food_id": food_id, "quantity": quantity, "unit": unit, "meal": meal,
                                         "consumed_at": when.isoformat()})
    assert resp.status_code in (200, 201), resp.text


@pytest.fixture
def setup(user_client):
    """Five logged days: plenty of vitamin C from food, too little iron, calcium and magnesium, no vitamin D data;
    a daily calcium supplement and a calming blend with ashwagandha."""
    c = user_client
    c.put("/api/profile", json=PROFILE)
    diet = _food(c, "Usual diet", {"energy_kcal": 270, "vitamin_c_mg": 40, "iron_mg": 0.4, "calcium_mg": 50,
                                   "magnesium_mg": 20})
    calcium = _food(c, "Calcium 600", {"calcium_mg": 600}, kind="supplement")
    calm = _food(c, "Calm blend", {}, kind="supplement",
                 other_components=[{"name": "Ashwagandha root extract", "amount": 150, "unit": "mg"}])
    for d in range(1, 6):
        _log(c, diet, d, 1000, "g")  # 2,700 kcal a day
        _log(c, calcium, d, 1, "serving", "supplement")
        _log(c, calm, d, 1, "serving", "supplement")
    multi = _food(c, "Multi", {"vitamin_c_mg": 100, "iron_mg": 18, "calcium_mg": 200, "magnesium_mg": 250,
                               "vitamin_d_ug": 25, "biotin_ug": 2},
                  kind="supplement", other_components=[
                      {"name": "Ashwagandha Root Extract", "amount": 300, "unit": "mg"},
                      {"name": "Vitamin A", "amount": 5000, "unit": "IU", "nutrient_code": "vitamin_a_ug"}])
    return c, {"diet": diet, "calcium": calcium, "calm": calm, "multi": multi}


def _rows(result):
    return {r["code"]: r for r in result["nutrients"]}


def test_check_judges_each_nutrient_against_food_and_other_supplements(setup):
    c, ids = setup
    result = c.post("/api/supplements/check", json={"food_id": ids["multi"]}).json()
    rows = _rows(result)
    assert result["window"]["logged_days"] == 5 and result["product"]["servings_per_day"] == 1
    assert rows["vitamin_c_mg"]["status"] == "covered_by_food" and rows["vitamin_c_mg"]["food"] == pytest.approx(400)
    assert rows["calcium_mg"]["status"] == "covered_by_supplements"
    assert rows["calcium_mg"]["also_in"] == ["Calcium 600"] and rows["calcium_mg"]["total_without"] == pytest.approx(1100)
    assert rows["iron_mg"]["status"] == "closes_gap" and rows["iron_mg"]["total_with"] == pytest.approx(22)
    assert rows["magnesium_mg"]["status"] == "closes_gap"
    assert rows["magnesium_mg"]["ul_scope"] == "supplemental" and rows["magnesium_mg"]["limit_amount_with"] == 250
    # No logged food reports vitamin D, so the gap is flagged as uncertain rather than stated flatly.
    assert rows["vitamin_d_ug"]["status"] == "closes_gap" and rows["vitamin_d_ug"]["uncertain"]
    assert rows["vitamin_d_ug"]["food_data_coverage"] == 0
    assert rows["biotin_ug"]["status"] == "minor"  # 2 µg against an AI of 30
    assert rows["vitamin_a_ug"]["status"] == "partial" and rows["vitamin_a_ug"]["uncounted"][0]["amount"] == 5000

    [ashwa] = result["other_ingredients"]
    assert ashwa["amount"] == 300 and ashwa["also_in"] == [{"label": "Calm blend", "amount": 150, "unit": "mg"}]

    v = result["verdict"]
    assert v["code"] == "partly_useful" and v["confidence"] == "normal"
    assert "Iron" in v["headline"] and "Magnesium" in v["headline"]
    assert v["counts"] == {"over_limit": 0, "gaps": 3, "covered": 2, "no_reference": 1}
    assert {s["label"] for s in result["other_supplements"]} == {"Calcium 600", "Calm blend"}
    assert any("can't account" in cav for cav in result["caveats"])


def test_double_dose_goes_over_a_supplement_only_limit(setup):
    c, ids = setup
    result = c.post("/api/supplements/check", json={"food_id": ids["multi"], "servings_per_day": 2}).json()
    mg = _rows(result)["magnesium_mg"]
    assert mg["status"] == "over_limit" and mg["limit_amount_with"] == 500 and mg["upper_limit"] == 350
    assert result["verdict"]["code"] == "caution" and "Magnesium" in result["verdict"]["headline"]


def test_product_already_taken_is_compared_without_itself(setup):
    c, ids = setup
    for d in (1, 2, 3):
        _log(c, ids["multi"], d, 2, "serving", "supplement")
    result = c.post("/api/supplements/check", json={"food_id": ids["multi"]}).json()
    assert result["already_taking"] == {"days_taken": 3, "servings_per_day": 2}
    assert result["product"]["servings_per_day"] == 2  # the usual dose
    iron = _rows(result)["iron_mg"]
    assert iron["food"] == pytest.approx(4) and iron["other_supplements"] == 0  # its own iron isn't in the baseline
    assert "Multi" not in {s["label"] for s in result["other_supplements"]}


def test_stack_checks_each_supplement_against_the_rest(setup):
    c, ids = setup
    _log(c, ids["multi"], 1, 1, "serving", "supplement")
    stack = c.get("/api/supplements/stack").json()
    by_label = {i["label"]: i for i in stack["items"]}
    assert set(by_label) == {"Calcium 600", "Calm blend", "Multi"}
    assert by_label["Calcium 600"]["days_taken"] == 5
    # Without the calcium supplement, food plus the multi still leaves calcium short: it's doing something.
    assert by_label["Calcium 600"]["verdict"]["code"] == "useful"
    assert by_label["Calm blend"]["verdict"]["code"] == "unclear"


def test_low_confidence_when_logging_looks_incomplete(user_client):
    c = user_client
    c.put("/api/profile", json=PROFILE)
    snack = _food(c, "Snack", {"energy_kcal": 100, "iron_mg": 1})
    iron = _food(c, "Iron 18", {"iron_mg": 18}, kind="supplement")
    _log(c, snack, 1, 200, "g")
    v = c.post("/api/supplements/check", json={"food_id": iron}).json()["verdict"]
    assert v["confidence"] == "low" and len(v["confidence_reasons"]) == 2


def test_without_profile_need_is_unknown(user_client):
    iron = _food(user_client, "Iron 18", {"iron_mg": 18}, kind="supplement")
    result = user_client.post("/api/supplements/check", json={"food_id": iron}).json()
    assert result["verdict"]["code"] == "unknown" and result["warnings"]


def test_other_users_private_product_is_not_found(setup, client):
    c, ids = setup
    c.post("/api/auth/logout")
    register(client, "b@example.com")
    assert client.post("/api/supplements/check", json={"food_id": ids["multi"]}).status_code == 404


def test_advisor_tool(setup, db_session):
    import json

    from app.advisor.tools import TOOLS, run_tool
    from app.models import User

    c, ids = setup
    assert any(t["name"] == "check_supplement" for t in TOOLS)
    user = db_session.query(User).filter_by(email="a@example.com").one()
    out = json.loads(run_tool(db_session, user, "check_supplement",
                              {"food_id": ids["multi"], "servings_per_day": 1, "days": 14}))
    assert out["verdict"]["code"] == "partly_useful"
    err = json.loads(run_tool(db_session, user, "check_supplement", {"food_id": 999999, "servings_per_day": 1, "days": 14}))
    assert "error" in err
