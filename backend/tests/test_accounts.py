import pytest

from app.models import PasswordReset
from app.security import login_throttle
from tests.conftest import register

PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _reset_throttle():
    login_throttle.failures.clear()
    yield
    login_throttle.failures.clear()


def use_cookie(client, cookie):
    client.cookies.clear()
    client.cookies.set("mp_session", cookie, domain="testserver.local")


def login(client, email="a@example.com", password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_password_change_signs_out_other_sessions(client):
    register(client)
    old_cookie = client.cookies.get("mp_session")
    assert client.put("/api/account/password", json={"current_password": "wrong one!!", "new_password": "x" * 12}
                      ).status_code == 403
    assert client.put("/api/account/password", json={"current_password": PW, "new_password": "new password 456"}
                      ).status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # this session got a fresh cookie
    use_cookie(client, old_cookie)
    assert client.get("/api/auth/me").status_code == 401  # the old one no longer works
    client.cookies.clear()
    assert login(client, password="new password 456").status_code == 200


def test_email_change_needs_password(client):
    register(client)
    register_b = client.post("/api/auth/register", json={"email": "b@example.com", "password": "another password"})
    assert register_b.status_code == 201
    client.cookies.clear()
    login(client)
    assert client.put("/api/account", json={"display_name": "A", "email": "new@example.com"}).status_code == 403
    assert client.put("/api/account", json={"display_name": "A", "email": "b@example.com",
                                            "current_password": PW}).status_code == 409
    resp = client.put("/api/account", json={"display_name": "Ann", "email": "New@Example.com", "current_password": PW})
    assert resp.json()["email"] == "new@example.com"


def test_login_throttle(client):
    register(client)
    client.cookies.clear()
    for _ in range(10):
        assert login(client, password="wrong password").status_code == 401
    assert login(client).status_code == 429  # even the right password, until the window passes


def test_admin_invite_and_reset_link(client, db_session):
    register(client, "admin@example.com")
    client.put("/api/admin/settings", json={"values": {"allow_registration": False}})
    invited = client.post("/api/admin/users", json={"email": "friend@example.com", "display_name": "Friend"}).json()
    assert invited["emailed"] is False and "/reset-password?token=" in invited["link"]
    token = invited["link"].split("token=")[1]
    assert db_session.query(PasswordReset).filter_by(token_hash=token).count() == 0  # only the hash is stored
    client.cookies.clear()
    resp = client.post("/api/auth/reset", json={"token": token, "new_password": "friend password 1"})
    assert resp.status_code == 200 and resp.json()["email"] == "friend@example.com"
    assert client.post("/api/auth/reset", json={"token": token, "new_password": "again password 2"}).status_code == 400
    client.cookies.clear()
    assert login(client, "friend@example.com", "friend password 1").status_code == 200


def test_admin_user_management_guards(client):
    admin = register(client, "admin@example.com")
    client.cookies.clear()
    user = register(client, "user@example.com")
    user_cookie = client.cookies.get("mp_session")
    client.cookies.clear()
    login(client, "admin@example.com")
    assert client.patch(f"/api/admin/users/{admin['id']}", json={"is_admin": False}).status_code == 409  # last admin
    assert client.delete(f"/api/admin/users/{admin['id']}").status_code == 409  # not yourself here
    rows = {u["email"]: u for u in client.get("/api/admin/users").json()}
    assert rows["user@example.com"]["is_admin"] is False
    client.patch(f"/api/admin/users/{user['id']}", json={"is_active": False})
    use_cookie(client, user_cookie)
    assert client.get("/api/auth/me").status_code == 401  # deactivation ends their sessions
    client.cookies.clear()
    assert login(client, "user@example.com").status_code == 401
    login(client, "admin@example.com")
    assert client.delete(f"/api/admin/users/{user['id']}").status_code == 204
    assert [u["email"] for u in client.get("/api/admin/users").json()] == ["admin@example.com"]


def test_forgot_password_does_not_reveal_accounts(client):
    register(client)
    client.cookies.clear()
    a = client.post("/api/auth/forgot", json={"email": "a@example.com"})
    b = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json() == {"email_enabled": False}


def test_export_and_delete_account(client):
    register(client)
    food = client.post("/api/foods", json={"name": "Oats", "nutrients": {"energy_kcal": 380}}).json()
    client.post("/api/recipes", json={"name": "Porridge", "servings": 1, "ingredients": [{"food_id": food["id"], "grams": 50}]})
    client.post("/api/log", json={"food_id": food["id"], "quantity": 50})
    export = client.get("/api/account/export")
    assert "attachment" in export.headers["content-disposition"]
    data = export.json()
    assert [f["name"] for f in data["foods"]] == ["Oats"] and len(data["log"]) == 1 and data["recipes"][0]["name"] == "Porridge"
    assert client.request("DELETE", "/api/account", json={"password": "nope nope"}).status_code == 403
    # the only admin can't delete themselves while others depend on an admin existing
    client.cookies.clear()
    register(client, "b@example.com")
    assert client.request("DELETE", "/api/account", json={"password": PW}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, "b@example.com").status_code == 401


def test_smtp_settings_accept_display_names(user_client):
    resp = user_client.put("/api/admin/settings", json={"values": {
        "smtp_host": "smtp.example.com", "smtp_from": "Mealplan <noreply@example.com>", "smtp_password": "s3cret!"}})
    assert resp.status_code == 200, resp.text
    assert user_client.get("/api/app-info").json()["email_enabled"] is True
    assert user_client.put("/api/admin/settings", json={"values": {"smtp_password": "has space"}}).status_code == 422
    result = user_client.post("/api/admin/settings/test-email").json()
    assert result["ok"] is False and "Sending failed" in result["message"]  # no server at smtp.example.com


def test_cli_reset_link_and_make_admin(client, db_session, monkeypatch, capsys):
    from app import cli

    register(client, "admin@example.com")
    client.cookies.clear()
    register(client, "user@example.com")
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    assert cli.main(["reset-link", "nobody@example.com"]) == 1
    assert cli.main(["reset-link", "admin@example.com", "--base-url", "https://meals.example.com/"]) == 0
    link = capsys.readouterr().out.strip()
    assert link.startswith("https://meals.example.com/reset-password?token=")
    client.cookies.clear()
    ok = client.post("/api/auth/reset", json={"token": link.split("token=")[1], "new_password": "recovered pass 1"})
    assert ok.status_code == 200
    assert cli.main(["make-admin", "user@example.com"]) == 0
    assert [u for u in client.get("/api/admin/users").json() if u["email"] == "user@example.com"][0]["is_admin"]
