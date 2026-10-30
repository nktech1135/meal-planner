from datetime import UTC, datetime

import httpx
from sqlalchemy import select
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


def upsert_external_food(db: Session, ext: ExternalFood) -> Food:
    """Store an imported record as a shared food, replacing any earlier copy of it."""
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
    food.trust_level = str(ext.trust_level)
    food.citation = ext.citation
    food.other_components = ext.other_components
    food.source_payload = ext.payload
    food.fetched_at = datetime.now(UTC)
    # Delete old child rows before inserting replacements (nutrients have a natural key).
    food.nutrients.clear()
    food.portions.clear()
    db.flush()
    food.nutrients = [FoodNutrient(nutrient_code=c, amount=a, derivation=d) for c, (a, d) in ext.nutrients.items()]
    food.portions = [FoodPortion(label=label[:200], gram_weight=g) for label, g in ext.portions]
    db.commit()
    db.refresh(food)
    return food
