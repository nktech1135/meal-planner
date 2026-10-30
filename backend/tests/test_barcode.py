import httpx
import pytest
import respx

from app.config import Settings
from app.main import app
from app.models import Food
from app.routers.sources import get_sources
from app.sources.base import ExternalFood, normalize_barcode
from app.sources.registry import build_sources, bulk_upsert_external_foods


@pytest.mark.parametrize("raw,expected", [
    ("012345678905", "12345678905"),     # UPC-A
    ("0012345678905", "12345678905"),    # the same product as EAN-13
    ("00012345678905", "12345678905"),   # and as GTIN-14
    ("4006381333931", "4006381333931"),  # EAN-13
    ("12 34", None), ("", None), (None, None),
])
def test_normalize_barcode(raw, expected):
    assert normalize_barcode(raw) == expected


def branded(fdc_id: int, gtin: str, name="Granola"):
    return {"fdcId": fdc_id, "description": name, "dataType": "Branded", "gtinUpc": gtin, "brandOwner": "Acme",
            "brandedFoodCategory": "Cereal", "ingredients": "OATS, HONEY.", "servingSize": 40, "servingSizeUnit": "g",
            "householdServingFullText": "0.5 cup",
            "foodNutrients": [{"nutrient": {"number": "208", "unitName": "kcal"}, "amount": 450},
                              {"nutrient": {"number": "203", "unitName": "g"}, "amount": 10}]}


def test_local_barcode_lookup_matches_any_gtin_form(user_client, db_session):
    from app.sources.usda_fdc import parse_fdc_food

    bulk_upsert_external_foods(db_session, [parse_fdc_food(branded(9001, "00012345678905"))])
    db_session.commit()
    found = user_client.get("/api/sources/barcode/012345678905").json()
    assert found["found_in"] == "local" and found["foods"][0]["barcode"] == "12345678905"
    assert found["foods"][0]["category"] == "Cereal"
    detail = user_client.get(f"/api/foods/{found['foods'][0]['id']}").json()
    assert detail["ingredients"] == "OATS, HONEY." and detail["trust_level"] == "label"
    assert user_client.get("/api/sources/barcode/abc").status_code == 422


@respx.mock
def test_barcode_falls_back_to_usda_online_and_saves(user_client, db_session):
    app.dependency_overrides[get_sources] = lambda: build_sources(
        Settings(usda_fdc_api_key="K", _env_file=None), httpx.Client())
    respx.get("https://api.nal.usda.gov/fdc/v1/foods/search").respond(json={"foods": [
        {"fdcId": 1, "gtinUpc": "099999999999"}, {"fdcId": 777, "gtinUpc": "0041196910759"}]})
    respx.get("https://api.nal.usda.gov/fdc/v1/food/777").respond(json=branded(777, "0041196910759", "Peanut butter"))
    found = user_client.get("/api/sources/barcode/041196910759").json()
    assert found["found_in"] == "usda_fdc" and found["foods"][0]["name"] == "Peanut butter"
    again = user_client.get("/api/sources/barcode/41196910759").json()
    assert again["found_in"] == "local"  # saved for next time


def test_unknown_barcode_with_no_online_sources(user_client):
    app.dependency_overrides[get_sources] = lambda: {}
    found = user_client.get("/api/sources/barcode/123456789012").json()
    assert found == {"barcode": "123456789012", "found_in": None, "foods": [], "errors": []}


def test_bulk_upsert_keeps_ids_and_replaces_children(db_session):
    def ext(name, kcal):
        return ExternalFood(source="test", source_id="A1", name=name, trust_level="analytical",
                            nutrients={"energy_kcal": (kcal, None)}, portions=[("1 cup", 100.0)])
    bulk_upsert_external_foods(db_session, [ext("First", 100)])
    db_session.commit()
    first = db_session.query(Food).filter_by(source="test").one()
    bulk_upsert_external_foods(db_session, [ext("Second", 200), ext("Second", 200)])  # duplicate in batch
    db_session.commit()
    db_session.expire_all()
    again = db_session.query(Food).filter_by(source="test").one()
    assert again.id == first.id and again.name == "Second"
    assert again.nutrient_map() == {"energy_kcal": 200} and len(again.portions) == 1


def test_manual_food_with_barcode_is_found_by_scan(user_client):
    food = user_client.post("/api/foods", json={"name": "Local bakery bread", "barcode": "0 12345 67890 5",
                                                "ingredients": "Flour, water, salt", "nutrients": {"energy_kcal": 250}}).json()
    assert food["barcode"] == "12345678905" and food["ingredients"] == "Flour, water, salt"
    found = user_client.get("/api/sources/barcode/012345678905").json()
    assert found["found_in"] == "local" and found["foods"][0]["id"] == food["id"]
