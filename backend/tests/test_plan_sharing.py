from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import register

TODAY = date.today().isoformat()
RANGE = {"start": TODAY, "end": TODAY}


@pytest.fixture
def people(client):
    """Alice (the first account, so admin), Bob and Carol, each signed in on their own client."""
    register(client, "alice@example.com")
    bob, carol = TestClient(app), TestClient(app)
    ids = {"alice": client.get("/api/auth/me").json()["id"]}
    for name, c in (("bob", bob), ("carol", carol)):
        register(c, f"{name}@example.com")
        ids[name] = c.get("/api/auth/me").json()["id"]
    oats = client.post("/api/foods", json={"name": "Oats", "nutrients": {"energy_kcal": 380}}).json()
    return {"alice": client, "bob": bob, "carol": carol, "ids": ids, "oats": oats}


def _share_oats(db_session, food_id):
    """Make it like an imported database food: visible to everyone."""
    from app.models import Food

    db_session.get(Food, food_id).owner_id = None
    db_session.commit()


def _item(food_id, **extra):
    return {"date": TODAY, "meal": "breakfast", "food_id": food_id, "quantity": 50, "unit": "g", **extra}


def test_editor_can_see_and_change_a_shared_plan(people, db_session):
    alice, bob, ids = people["alice"], people["bob"], people["ids"]
    _share_oats(db_session, people["oats"]["id"])
    alice_soup = alice.post("/api/recipes", json={"name": "Alice's soup", "servings": 2, "ingredients": [
        {"food_id": people["oats"]["id"], "grams": 100}]}).json()
    bob_food = bob.post("/api/foods", json={"name": "Bob's bar", "nutrients": {"energy_kcal": 400}}).json()

    assert bob.get("/api/plan", params={**RANGE, "of": ids["alice"]}).status_code == 404  # not shared yet
    shares = alice.put("/api/plan-shares", json={"email": "bob@example.com", "can_edit": True}).json()
    assert shares["shared_with"][0]["email"] == "bob@example.com" and shares["shared_with"][0]["can_edit"]
    assert bob.get("/api/plan-shares").json()["shared_with_me"][0]["user_id"] == ids["alice"]

    of = {"of": ids["alice"]}
    added = bob.post("/api/plan", params=of, json=_item(people["oats"]["id"]))
    assert added.status_code == 201, added.text
    # Alice's own recipes are available to Bob for her plan, his private foods aren't.
    assert [r["name"] for r in bob.get("/api/recipes", params={"for_user": ids["alice"]}).json()] == ["Alice's soup"]
    assert bob.post("/api/plan", params=of, json={"date": TODAY, "meal": "dinner", "recipe_id": alice_soup["id"],
                                                  "quantity": 1, "unit": "serving"}).status_code == 201
    assert bob.post("/api/plan", params=of, json=_item(bob_food["id"])).status_code == 404

    [day] = alice.get("/api/plan", params=RANGE).json()
    assert {i["label"] for i in day["items"]} == {"Oats", "Alice's soup"}
    assert all(i["added_by"] == "A" for i in day["items"])  # display name from register()
    item_id = added.json()["id"]
    assert bob.patch(f"/api/plan/{item_id}", params=of, json={"quantity": 80}).json()["quantity"] == 80
    # Logging writes to Alice's food log, which isn't shared: only she can do it.
    assert bob.post(f"/api/plan/{item_id}/log").status_code == 404
    assert alice.post(f"/api/plan/{item_id}/log").status_code == 201

    shopping = bob.get("/api/plan/shopping", params={**RANGE, "of": ids["alice"], "include_logged": True}).json()
    key = next(i["key"] for i in shopping["items"] if i["name"] == "Oats")
    assert bob.put("/api/plan/shopping/check", params=of,
                   json={"start": TODAY, "end": TODAY, "key": key, "checked": True}).status_code == 204
    mine = alice.get("/api/plan/shopping", params={**RANGE, "include_logged": True}).json()
    assert next(i for i in mine["items"] if i["key"] == key)["checked"]  # one list for the household

    assert bob.delete(f"/api/plan/{item_id}", params=of).status_code == 204
    # Bob's own plan is untouched by all this.
    assert bob.get("/api/plan", params=RANGE).json()[0]["items"] == []


def test_view_only_share_and_revoking(people, db_session):
    alice, bob, carol, ids = people["alice"], people["bob"], people["carol"], people["ids"]
    _share_oats(db_session, people["oats"]["id"])
    alice.post("/api/plan", json=_item(people["oats"]["id"]))
    alice.put("/api/plan-shares", json={"email": "bob@example.com", "can_edit": False})
    of = {"of": ids["alice"]}
    assert len(bob.get("/api/plan", params={**RANGE, **of}).json()[0]["items"]) == 1
    denied = bob.post("/api/plan", params=of, json=_item(people["oats"]["id"]))
    assert denied.status_code == 403 and "view only" in denied.json()["detail"]
    # Someone it wasn't shared with can't see the plan or read her private foods through it.
    assert carol.get("/api/plan", params={**RANGE, **of}).status_code == 404
    assert carol.get("/api/foods", params={"for_user": ids["alice"]}).status_code == 404

    assert alice.delete(f"/api/plan-shares/{ids['bob']}").status_code == 204
    assert bob.get("/api/plan", params={**RANGE, **of}).status_code == 404

    alice.put("/api/plan-shares", json={"email": "carol@example.com"})
    assert carol.delete(f"/api/plan-shares/from/{ids['alice']}").status_code == 204  # Carol leaves
    assert alice.get("/api/plan-shares").json()["shared_with"] == []


def test_sharing_rejects_unknown_self_and_deactivated(people):
    alice, bob, ids = people["alice"], people["bob"], people["ids"]
    assert alice.put("/api/plan-shares", json={"email": "nobody@example.com"}).status_code == 404
    assert alice.put("/api/plan-shares", json={"email": "alice@example.com"}).status_code == 422
    bob.put("/api/plan-shares", json={"email": "alice@example.com"})
    assert alice.get("/api/plan", params={**RANGE, "of": ids["bob"]}).status_code == 200
    alice.patch(f"/api/admin/users/{ids['bob']}", json={"is_active": False})
    assert alice.get("/api/plan", params={**RANGE, "of": ids["bob"]}).status_code == 404
    assert alice.get("/api/plan-shares").json()["shared_with_me"] == []


def test_admin_adds_user_with_password_and_sets_up_sharing(people):
    alice, ids = people["alice"], people["ids"]
    resp = alice.post("/api/admin/users", json={"email": "Dan@Example.com", "display_name": "Dan",
                                                 "password": "dans password 1"})
    assert resp.status_code == 201 and resp.json()["link"] is None
    dan_id = resp.json()["user"]["id"]
    dan = TestClient(app)
    assert dan.post("/api/auth/login", json={"email": "dan@example.com", "password": "dans password 1"}).status_code == 200
    assert alice.post("/api/admin/users", json={"email": "e@example.com", "password": "short"}).status_code == 422
    admin2 = alice.post("/api/admin/users", json={"email": "f@example.com", "password": "long enough pw", "is_admin": True})
    assert admin2.json()["user"]["is_admin"]

    # The admin lets Bob plan Dan's meals without Dan having to do it himself.
    shares = alice.put(f"/api/admin/users/{dan_id}/plan-shares", json={"email": "bob@example.com"}).json()
    assert shares["shared_with"][0]["user_id"] == ids["bob"]
    assert people["bob"].get("/api/plan", params={**RANGE, "of": dan_id}).status_code == 200
    assert people["bob"].get(f"/api/admin/users/{dan_id}/plan-shares").status_code == 403
    assert alice.delete(f"/api/admin/users/{dan_id}/plan-shares/{ids['bob']}").status_code == 204
    assert people["bob"].get("/api/plan", params={**RANGE, "of": dan_id}).status_code == 404

    # Without a password it's still an invite with a link.
    invite = alice.post("/api/admin/users", json={"email": "g@example.com"}).json()
    assert invite["link"] and "reset-password?token=" in invite["link"]
