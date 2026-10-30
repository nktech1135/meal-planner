from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Food, FoodNutrient, FoodPortion
from app.sources.base import DataSource, ExternalFood
from app.sources.edamam import Edamam
from app.sources.nih_dsld import NihDsld
from app.sources.nutritionix import Nutritionix
from app.sources.open_food_facts import OpenFoodFacts
from app.sources.usda_fdc import UsdaFdc

SOURCE_CLASSES: list[type[DataSource]] = [UsdaFdc, NihDsld, Nutritionix, Edamam, OpenFoodFacts]

_client: httpx.Client | None = None


def http_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(follow_redirects=True)
    return _client


def build_sources(settings: Settings, client: httpx.Client | None = None) -> dict[str, DataSource]:
    client = client or http_client()
    return {cls.key: cls(settings, client) for cls in SOURCE_CLASSES}


def upsert_external_food(db: Session, ext: ExternalFood, commit: bool = True) -> Food:
    """Store an imported record as a shared food, replacing any earlier copy of it.

    Bulk imports pass ``commit=False`` and commit in batches themselves.
    """
    food = db.scalar(select(Food).where(Food.source == ext.source, Food.source_id == ext.source_id))
    if food is None:
        food = Food(source=ext.source, source_id=ext.source_id, owner_id=None)
        db.add(food)
    food.name = ext.name[:300]
    food.brand = ext.brand
    food.kind = ext.kind
    food.state = ext.state
    food.cooking_method = ext.cooking_method
    food.basis = ext.basis
    food.serving_quantity = ext.serving_quantity
    food.serving_unit = ext.serving_unit
    food.serving_size_g = ext.serving_size_g
    food.source_url = ext.source_url
    food.source_data_type = ext.data_type
    food.category = ext.category
    food.barcode = ext.barcode
    food.ingredients = ext.ingredients
    food.trust_level = str(ext.trust_level)
    food.citation = ext.citation
    food.other_components = ext.other_components
    food.source_payload = ext.payload
    food.fetched_at = datetime.now(UTC)
    # Delete old child rows before inserting replacements (nutrients have a natural key).
    food.nutrients.clear()
    food.portions.clear()
    db.flush()
    food.nutrients = [FoodNutrient(nutrient_code=c, amount=a, derivation=d[:120] if d else d)
                      for c, (a, d) in ext.nutrients.items()]
    food.portions = [FoodPortion(label=label[:200], gram_weight=g) for label, g in ext.portions]
    if commit:
        db.commit()
        db.refresh(food)
    else:
        db.flush()
    return food


def _food_columns(ext: ExternalFood, now: datetime) -> dict:
    return {
        "name": ext.name[:300], "brand": (ext.brand or None) and ext.brand[:200], "kind": ext.kind, "state": ext.state,
        "cooking_method": ext.cooking_method, "basis": ext.basis, "serving_quantity": ext.serving_quantity,
        "serving_unit": ext.serving_unit, "serving_size_g": ext.serving_size_g, "source_url": ext.source_url,
        "source_data_type": ext.data_type, "category": ext.category and ext.category[:120], "barcode": ext.barcode,
        "ingredients": ext.ingredients, "trust_level": str(ext.trust_level), "citation": ext.citation,
        "other_components": ext.other_components, "source_payload": ext.payload, "fetched_at": now,
    }


def bulk_upsert_external_foods(db: Session, exts: list[ExternalFood]) -> int:
    """Set-based version of upsert_external_food for dataset imports (one source per call).

    Existing records (same source and source_id) are updated in place, so their ids, and
    the log entries, recipes and yields pointing at them, stay valid. Not committed.
    """
    batch = list({e.source_id: e for e in exts}.values())
    if not batch:
        return 0
    source = batch[0].source
    now = datetime.now(UTC)
    ids = dict(db.execute(select(Food.source_id, Food.id).where(
        Food.source == source, Food.source_id.in_([e.source_id for e in batch]))).all())
    existing = [e for e in batch if e.source_id in ids]
    if existing:
        old_ids = [ids[e.source_id] for e in existing]
        db.execute(delete(FoodNutrient).where(FoodNutrient.food_id.in_(old_ids)))
        db.execute(delete(FoodPortion).where(FoodPortion.food_id.in_(old_ids)))
        db.execute(update(Food), [{"id": ids[e.source_id], **_food_columns(e, now)} for e in existing])
    new = [e for e in batch if e.source_id not in ids]
    if new:
        rows = db.execute(insert(Food).returning(Food.id, Food.source_id), [
            {**_food_columns(e, now), "source": source, "source_id": e.source_id, "owner_id": None, "created_at": now}
            for e in new]).all()
        ids.update({source_id: food_id for food_id, source_id in rows})
    nutrients = [{"food_id": ids[e.source_id], "nutrient_code": code, "amount": amount,
                  "derivation": derivation[:120] if derivation else derivation}
                 for e in batch for code, (amount, derivation) in e.nutrients.items()]
    if nutrients:
        db.execute(insert(FoodNutrient), nutrients)
    portions = [{"food_id": ids[e.source_id], "label": label[:200], "gram_weight": grams}
                for e in batch for label, grams in e.portions]
    if portions:
        db.execute(insert(FoodPortion), portions)
    return len(batch)
