from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app

TODAY = date.today().isoformat()
PROFILE = "X-Mealplan-Profile"


def _signup(c: TestClient, email: str, name: str) -> int:
    resp = c.post("/api/auth/register", json={"email": email, "password": "correct horse battery", "display_name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def people(client):
    """Alice (the first account, so admin), Bob and Carol, each signed in on their own client."""
    bob, carol = TestClient(app), TestClient(app)
    ids = {"alice": _signup(client, "alice@example.com", "Alice"), "bob": _signup(bob, "bob@example.com", "Bob"),
           "carol": _signup(carol, "carol@example.com", "Carol")}
    return {"alice": client, "bob": bob, "carol": carol, "ids": ids}


def _as(owner_id: int) -> dict:
    return {"headers": {PROFILE: str(owner_id)}}


def _log(c: TestClient, food_id: int, **kw):
    return c.post("/api/log", json={"food_id": food_id, "quantity": 100, "unit": "g", "meal": "breakfast"}, **kw)


def test_full_access_works_on_the_owners_data(people):
    alice, bob, ids = people["alice"], people["bob"], people["ids"]
    as_alice = _as(ids["alice"])
    alice_food = alice.post("/api/foods", json={"name": "Alice's granola", "nutrients": {"energy_kcal": 450}}).json()
    bob_food = bob.post("/api/foods", json={"name": "Bob's bar", "nutrients": {"energy_kcal": 400}}).json()

    assert bob.get("/api/profile", **as_alice).status_code == 403  # not shared yet
    shares = alice.put("/api/profile-access", json={"email": "bob@example.com"}).json()
    assert shares["shared_with"][0]["name"] == "Bob" and shares["shared_with"][0]["can_edit"]
    assert bob.get("/api/profile-access").json()["shared_with_me"][0]["user_id"] == ids["alice"]

    # Bob, using Alice's profile, sees and changes her data as if he were her...
    assert bob.put("/api/profile", json={"weight_kg": 61, "goal": "lose"}, **as_alice).status_code == 200
    assert alice.get("/api/profile").json()["weight_kg"] == 61
    assert [f["name"] for f in bob.get("/api/foods", params={"mine": True}, **as_alice).json()] == ["Alice's granola"]
    assert _log(bob, bob_food["id"], **as_alice).status_code == 404  # his own private food isn't hers
    logged = _log(bob, alice_food["id"], **as_alice)
    assert logged.status_code == 201 and logged.json()["added_by"] == "Bob"

    # ...and she sees what he logged for her, marked as his doing.
    [entry] = alice.get("/api/summary/day", params={"date": TODAY}).json()["entries"]
    assert entry["label"] == "Alice's granola" and entry["added_by"] == "Bob"
    assert _log(alice, alice_food["id"]).json()["added_by"] is None
    # Bob's own profile is untouched.
    assert bob.get("/api/summary/day", params={"date": TODAY}).json()["entries"] == []
    assert bob.get("/api/profile").json()["weight_kg"] is None


def test_account_admin_and_sharing_stay_the_signed_in_persons(people):
    alice, bob, ids = people["alice"], people["bob"], people["ids"]
    bob.put("/api/profile-access", json={"email": "alice@example.com"})
    alice.put("/api/profile-access", json={"email": "bob@example.com"})
    as_alice, as_bob = _as(ids["alice"]), _as(ids["bob"])

    assert bob.get("/api/auth/me", **as_alice).json()["email"] == "bob@example.com"
    # Alice is an admin, Bob isn't: using her profile doesn't make him one.
    assert bob.get("/api/admin/users", **as_alice).status_code == 403
    assert alice.get("/api/admin/users", **as_bob).status_code == 200
    assert bob.put("/api/account", json={"display_name": "Robert", "email": "bob@example.com"}, **as_alice).status_code == 200
    assert alice.get("/api/auth/me").json()["display_name"] == "Alice"
    # Only Alice decides who sees her plan; Bob can read the list, for the plan page.
    assert bob.put("/api/plan-shares", json={"email": "carol@example.com"}, **as_alice).status_code == 403
    assert bob.get("/api/plan-shares", **as_alice).status_code == 200
    # Profile access is always about the signed-in person, header or not.
    bob.put("/api/profile-access", json={"email": "carol@example.com"}, **as_alice)
    assert [p["name"] for p in alice.get("/api/profile-access").json()["shared_with"]] == ["Robert"]
    assert {p["name"] for p in bob.get("/api/profile-access").json()["shared_with"]} == {"Alice", "Carol"}


def test_view_only_access(people):
    alice, carol, ids = people["alice"], people["carol"], people["ids"]
    food = alice.post("/api/foods", json={"name": "Oats", "nutrients": {"energy_kcal": 380}}).json()
    _log(alice, food["id"])
    alice.put("/api/profile-access", json={"email": "carol@example.com", "can_edit": False})
    as_alice = _as(ids["alice"])

    assert len(carol.get("/api/summary/day", params={"date": TODAY}, **as_alice).json()["entries"]) == 1
    denied = _log(carol, food["id"], **as_alice)
    assert denied.status_code == 403 and "view only" in denied.json()["detail"]
    assert carol.put("/api/profile", json={"weight_kg": 50}, **as_alice).status_code == 403
    # Calculations that change nothing are still allowed.
    calc = carol.post("/api/nutrition/calculate", json={"food_id": food["id"], "quantity": 50, "unit": "g"}, **as_alice)
    assert calc.status_code == 200 and calc.json()["nutrients"]["energy_kcal"] == 190


def test_revoked_unshared_and_deactivated(people):
    alice, bob, carol, ids = people["alice"], people["bob"], people["carol"], people["ids"]
    as_alice = _as(ids["alice"])
    gone = carol.get("/api/profile", **as_alice)
    assert gone.status_code == 403 and gone.headers["X-Mealplan-Profile-Gone"] == "1"
    assert carol.get("/api/profile", headers={PROFILE: "nope"}).status_code == 400
    assert carol.get("/api/profile", **_as(ids["carol"])).status_code == 200  # your own id is fine

    alice.put("/api/profile-access", json={"email": "bob@example.com"})
    assert bob.get("/api/profile", **as_alice).status_code == 200
    assert alice.delete(f"/api/profile-access/{ids['bob']}").status_code == 204
    assert bob.get("/api/profile", **as_alice).headers.get("X-Mealplan-Profile-Gone") == "1"

    alice.put("/api/profile-access", json={"email": "bob@example.com"})
    assert bob.delete(f"/api/profile-access/from/{ids['alice']}").status_code == 204  # Bob gives it up
    assert bob.get("/api/profile-access").json()["shared_with_me"] == []

    # An admin sets it up for others; a deactivated owner's profile can't be used.
    assert alice.put(f"/api/admin/users/{ids['carol']}/profile-access", json={"email": "bob@example.com"}).status_code == 200
    assert bob.get("/api/profile", **_as(ids["carol"])).status_code == 200
    assert bob.get(f"/api/admin/users/{ids['carol']}/profile-access").status_code == 403
    alice.patch(f"/api/admin/users/{ids['carol']}", json={"is_active": False})
    assert bob.get("/api/profile", **_as(ids["carol"])).status_code == 403
    assert bob.get("/api/profile-access").json()["shared_with_me"] == []
