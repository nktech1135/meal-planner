import gzip
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from app.advisor.tools import run_tool
from app.models import User
from app.services import exercise as svc
from tests.conftest import FIXTURES, register
from tests.test_api import create_food

TODAY = datetime.now(UTC).date()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
def client(user_client):
    user_client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "height_cm": 180, "weight_kg": 80,
                                          "timezone": "UTC"})
    return user_client


def energy_target(client, day=TODAY) -> dict:
    summary = client.get("/api/summary/day", params={"day": day.isoformat()}).json()
    return {r["code"]: r for r in summary["evaluation"]}


def test_compendium_data():
    data = svc.compendium()
    assert len(data) == 1111
    assert data["02050"].met == 6.0 and data["02050"].description.endswith("vigorous effort (Taylor Code 210)")
    assert data["12150"].description == "Running (Taylor Code 200)" and data["12150"].met == 8.0
    assert all(code in data for code in svc.SPORT_CODES.values())
    assert [a.code for a in svc.search_activities("yoga power")] == ["02160"]
    assert svc.activity_for_sport("cycling", "mountain").code == "01009"
    assert svc.activity_for_sport("Biking").code == "01014"
    assert svc.activity_for_sport("Other") is None


def test_estimate():
    met = svc.estimate(8.0, 30, 80, None)
    assert met["kcal"] == 280 and met["kcal_method"] == "compendium"  # (8 - 1) × 80 kg × 0.5 h
    device = svc.estimate(None, 60, 70, 500)
    assert device["kcal"] == 430 and device["kcal_method"] == "device"  # 500 - 1 × 70 × 1
    assert svc.estimate(None, 60, None, 500)["kcal"] == 500
    assert svc.estimate(8.0, 30, None, None)["kcal"] == 0
    assert svc.estimate(None, 600, 80, 100)["kcal"] == 0  # never negative


def test_manual_exercise_raises_energy_target(client):
    before = energy_target(client)
    resp = client.post("/api/exercise", json={"date": TODAY.isoformat(), "activity_code": "12150", "duration_min": 45})
    assert resp.status_code == 201, resp.text
    ex = resp.json()
    assert ex["name"] == "Running (Taylor Code 200)" and ex["met"] == 8.0 and ex["weight_kg"] == 80
    assert ex["kcal"] == 420 and ex["kcal_method"] == "compendium"  # (8 - 1) × 80 × 0.75
    assert "Compendium" in ex["calc_note"]

    after = energy_target(client)
    assert after["energy_kcal"]["target"] == before["energy_kcal"]["target"] + 420
    assert after["energy_kcal"]["exercise_kcal"] == 420
    assert after["carbs_g"]["max"] > before["carbs_g"]["max"]  # macro ranges scale with energy
    summary = client.get("/api/summary/day").json()
    assert summary["exercise_kcal"] == 420 and summary["exercises"][0]["id"] == ex["id"]
    assert energy_target(client, YESTERDAY)["energy_kcal"]["target"] == before["energy_kcal"]["target"]

    # A weigh-in on the day is used rather than the profile weight; entered calories win over METs.
    client.put(f"/api/body/{TODAY}", json={"weight_kg": 70})
    edited = client.put(f"/api/exercise/{ex['id']}", json={
        "date": TODAY.isoformat(), "activity_code": "12150", "duration_min": 60, "reported_kcal": 600,
        "note": "treadmill"}).json()
    assert edited["weight_kg"] == 70 and edited["kcal"] == 530 and edited["kcal_method"] == "entered"

    assert client.delete(f"/api/exercise/{ex['id']}").status_code == 204
    assert client.get("/api/exercise").json() == []


def test_energy_override_also_rises(client):
    client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "height_cm": 180, "weight_kg": 80,
                                     "timezone": "UTC", "target_overrides": {"energy_kcal": {"target": 2000}}})
    client.post("/api/exercise", json={"date": TODAY.isoformat(), "name": "Gym machine", "duration_min": 30,
                                       "reported_kcal": 340})
    assert energy_target(client)["energy_kcal"]["target"] == 2300  # 340 - 40 kcal resting


def test_validation(client):
    future = (TODAY + timedelta(days=1)).isoformat()
    assert client.post("/api/exercise", json={"date": future, "activity_code": "12150", "duration_min": 30}
                       ).status_code == 422
    assert client.post("/api/exercise", json={"date": TODAY.isoformat(), "activity_code": "99999", "duration_min": 30}
                       ).status_code == 422
    assert client.post("/api/exercise", json={"date": TODAY.isoformat(), "duration_min": 30}).status_code == 422
    assert client.post("/api/exercise", json={"date": TODAY.isoformat(), "name": "x", "duration_min": 0}
                       ).status_code == 422
    assert client.get("/api/exercise/activities", params={"q": "kettle bell swings"}).json()[0]["code"] == "02058"
    assert len(client.get("/api/exercise/activities").json()) > 10


FIT_DIR = FIXTURES / "exercise"
RUN_START = datetime(2026, 10, 30, 7, 15, tzinfo=UTC)  # run.fit


def tcx_file(start: datetime) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Biking"><Id>{start.isoformat().replace("+00:00", "Z")}</Id>
    <Lap StartTime="{start.isoformat()}"><TotalTimeSeconds>1200</TotalTimeSeconds><DistanceMeters>8000</DistanceMeters>
      <Calories>250</Calories><AverageHeartRateBpm><Value>130</Value></AverageHeartRateBpm></Lap>
    <Lap StartTime="{(start + timedelta(minutes=20)).isoformat()}"><TotalTimeSeconds>600</TotalTimeSeconds>
      <DistanceMeters>4000</DistanceMeters><Calories>150</Calories>
      <AverageHeartRateBpm><Value>160</Value></AverageHeartRateBpm></Lap>
  </Activity></Activities>
</TrainingCenterDatabase>""".encode()


def gpx_file(start: datetime) -> bytes:
    points = "".join(
        f'<trkpt lat="{51.5 + i * 0.001}" lon="-0.12"><time>{(start + timedelta(minutes=i)).isoformat()}</time>'
        f'<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>{100 + i}</gpxtpx:hr></gpxtpx:TrackPointExtension>'
        f'</extensions></trkpt>' for i in range(31))
    return f"""<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><name>Morning walk</name><type>walking</type><trkseg>{points}</trkseg></trk>
</gpx>""".encode()


def test_parsers():
    start = RUN_START
    [fit] = svc.parse_file("run.fit", (FIT_DIR / "run.fit").read_bytes())
    assert (fit.started_at, fit.sport, fit.duration_min, fit.distance_m, fit.avg_hr, fit.reported_kcal) == (
        start, "running", 30, 5000, 150, 420)
    swim, ride = svc.parse_file("tri.fit", (FIT_DIR / "multisport.fit").read_bytes())
    assert (swim.sport, swim.sub_sport, swim.duration_min, swim.reported_kcal) == ("swimming", "open_water", 25, None)
    assert svc.activity_for_sport(swim.sport, swim.sub_sport).code == "18300"
    assert (ride.sub_sport, ride.reported_kcal) == ("mountain", 700)
    with pytest.raises(svc.ActivityFileError):
        svc.parse_file("cut.fit", (FIT_DIR / "run.fit").read_bytes()[:-5])
    [tcx] = svc.parse_file("ride.tcx.gz", gzip.compress(tcx_file(start)))
    assert tcx.sport == "Biking" and tcx.duration_min == 30 and tcx.distance_m == 12000 and tcx.reported_kcal == 400
    assert tcx.avg_hr == pytest.approx(140)  # time-weighted over laps
    [gpx] = svc.parse_file("walk.gpx", gpx_file(start))
    assert gpx.sport == "walking" and gpx.duration_min == 30 and gpx.avg_hr == 115 and gpx.reported_kcal is None
    assert gpx.distance_m == pytest.approx(3336, rel=0.01)  # 30 × 0.001° of latitude
    for name, data in (("x.fit", b"not a fit file"), ("x.gpx", b"<gpx"), ("x.txt", b""), ("x.fit.gz", b"nope")):
        with pytest.raises(svc.ActivityFileError):
            svc.parse_file(name, data)
    with pytest.raises(svc.ActivityFileError):  # entity expansion is refused
        svc.parse_file("bomb.gpx", b'<?xml version="1.0"?><!DOCTYPE g [<!ENTITY a "aaaa">]><gpx>&a;</gpx>')


def test_import_files_and_archive(client):
    def at(day, hour):
        return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)

    run_fit = (FIT_DIR / "run.fit").read_bytes()
    run_day = RUN_START.date()
    ride, walk = at(YESTERDAY, 18), at(TODAY, 6)
    resp = client.post("/api/exercise/import", files=[
        ("files", ("run.fit", run_fit, "application/octet-stream")),
        ("files", ("ride.tcx", tcx_file(ride), "application/xml")),
        ("files", ("broken.gpx", b"<gpx><trk>", "application/xml")),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2 and body["error_count"] == 1 and body["errors"][0]["file"] == "broken.gpx"
    by_source = {e["source"]: e for e in body["exercises"]}
    assert by_source["fit"]["activity_code"] == "12150" and by_source["fit"]["kcal"] == 380  # 420 - 80 × 0.5
    assert by_source["fit"]["kcal_method"] == "device" and by_source["fit"]["date"] == run_day.isoformat()
    assert by_source["tcx"]["name"] == "Bicycling, general" and by_source["tcx"]["kcal"] == 360

    # A Strava-style export: gzipped files in activities/, plus files that aren't workouts.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("activities/1.fit.gz", gzip.compress(run_fit))  # duplicate of the run
        z.writestr("activities/2.gpx", gpx_file(walk))
        z.writestr("activities/3.gpx", gpx_file(at(run_day - timedelta(days=40), 9)))
        z.writestr("activities.csv", "id,name\n")
        z.writestr("media/photo.jpg", b"\xff\xd8")
    since = min(run_day, TODAY - timedelta(days=7)).isoformat()  # the duplicate run is still on or after it
    resp = client.post("/api/exercise/import", data={"since": since},
                       files=[("files", ("export.zip", archive.getvalue(), "application/zip"))])
    body = resp.json()
    assert (body["imported"], body["skipped_duplicates"], body["skipped_before_since"], body["error_count"]) == (1, 1, 1, 0)
    [walk_ex] = body["exercises"]
    assert walk_ex["source"] == "gpx" and walk_ex["kcal_method"] == "compendium"
    assert walk_ex["kcal"] == 120  # (4.0 - 1) × 80 kg × 0.5 h

    days = client.get("/api/exercise", params={"start": run_day.isoformat()}).json()
    assert [e["source"] for e in days] == ["gpx", "tcx", "fit"]  # newest first
    # Editing an imported workout keeps the device figure unless it changes.
    fit_ex = by_source["fit"]
    kept = client.put(f"/api/exercise/{fit_ex['id']}", json={**{k: fit_ex[k] for k in (
        "date", "started_at", "activity_code", "duration_min", "distance_m", "avg_hr", "reported_kcal")},
        "note": "easy"}).json()
    assert kept["kcal_method"] == "device" and kept["note"] == "easy"


def test_trends_use_each_days_target(client):
    food = create_food(client, name="Oats", nutrients={"energy_kcal": 100})
    for day, grams in ((TODAY, 2600), (YESTERDAY, 2600)):
        client.post("/api/log", json={"food_id": food["id"], "quantity": grams,
                                      "consumed_at": datetime(day.year, day.month, day.day, 12, tzinfo=UTC).isoformat()})
    base = energy_target(client)["energy_kcal"]["target"]
    client.post("/api/exercise", json={"date": YESTERDAY.isoformat(), "activity_code": "12150", "duration_min": 120})
    t = client.get("/api/trends", params={"days": 7}).json()
    assert t["exercise_kcal"] == {YESTERDAY.isoformat(): 1120.0}
    energy = next(r for r in t["evaluation"] if r["code"] == "energy_kcal")
    assert energy["target"] == round(base + 560)  # the average logged day's target


def test_advisor_tool_and_privacy(client, db_session):
    client.post("/api/exercise", json={"date": TODAY.isoformat(), "activity_code": "02150", "duration_min": 60})
    user = db_session.query(User).one()
    [row] = json.loads(run_tool(db_session, user, "get_exercise",
                                {"start_date": YESTERDAY.isoformat(), "end_date": TODAY.isoformat()}))
    assert row["activity"] == "Yoga, Hatha" and row["net_kcal"] == 104 and row["kcal_method"] == "compendium"
    summary = json.loads(run_tool(db_session, user, "get_day_summary", {"date": TODAY.isoformat()}))
    assert summary["net_exercise_kcal"] == 104

    [ex] = client.get("/api/exercise").json()
    client.cookies.clear()
    register(client, "b@example.com")
    assert client.get("/api/exercise").json() == []
    assert client.delete(f"/api/exercise/{ex['id']}").status_code == 404
