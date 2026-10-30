from app.models import AppSetting
from app.routers.sources import get_sources
from tests.conftest import register


def test_settings_are_admin_only(client):
    register(client, "admin@example.com")
    client.cookies.clear()
    register(client, "user@example.com")
    assert client.get("/api/admin/settings").status_code == 403
    assert client.put("/api/admin/settings", json={"values": {"allow_registration": False}}).status_code == 403


def test_secret_is_encrypted_masked_and_used(user_client, db_session):
    resp = user_client.put("/api/admin/settings", json={"values": {"usda_fdc_api_key": "abcdef1234567890WXYZ"}})
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["key"] == "usda_fdc_api_key")
    assert row["value"] == "••••••••WXYZ" and row["is_set"] and row["source"] == "settings"
    stored = db_session.get(AppSetting, "usda_fdc_api_key").value
    assert "abcdef" not in stored  # encrypted at rest
    # The effective value reaches the data sources.
    from app.settings_store import runtime_settings
    assert runtime_settings(db_session).usda_fdc_api_key == "abcdef1234567890WXYZ"
    assert user_client.get("/api/app-info").json()["usda_demo_key"] is False
    # Clearing falls back to the bootstrap default.
    user_client.put("/api/admin/settings", json={"values": {"usda_fdc_api_key": None}})
    assert user_client.get("/api/app-info").json()["usda_demo_key"] is True


def test_validation(user_client):
    bad = [{"advisor_effort": "extreme"}, {"advisor_daily_message_limit": 0}, {"allow_registration": "yes"},
           {"nope": 1}, {"anthropic_api_key": "two words"}]
    for values in bad:
        assert user_client.put("/api/admin/settings", json={"values": values}).status_code == 422, values


def test_registration_toggle(client):
    register(client, "admin@example.com")
    client.put("/api/admin/settings", json={"values": {"allow_registration": False}})
    assert client.get("/api/app-info").json()["allow_registration"] is False
    client.cookies.clear()
    resp = client.post("/api/auth/register", json={"email": "late@example.com", "password": "long enough pw"})
    assert resp.status_code == 403


def test_source_toggle_takes_effect(user_client):
    from app.main import app

    app.dependency_overrides.pop(get_sources, None)
    sources = {s["key"]: s for s in user_client.get("/api/sources").json()}
    assert sources["open_food_facts"]["enabled"] is False
    user_client.put("/api/admin/settings", json={"values": {"enable_unverified_sources": True}})
    sources = {s["key"]: s for s in user_client.get("/api/sources").json()}
    assert sources["open_food_facts"]["enabled"] is True


def test_anthropic_test_without_key(user_client):
    resp = user_client.post("/api/admin/settings/test/anthropic").json()
    assert resp == {"ok": False, "message": "No Anthropic API key set"}
