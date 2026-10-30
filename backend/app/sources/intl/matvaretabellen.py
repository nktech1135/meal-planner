"""Norwegian food composition table (Matvaretabellen, Norwegian Food Safety Authority), English JSON API.

Files:

- ``foods``: {"foods": [{foodId, foodName, foodGroupId, uri, energy {kJ}, calories {kcal}, portions,
  constituents: [{nutrientId, quantity, unit, sourceId}]}]}; a constituent without a quantity is missing
  (sourceId "10": "content not known").
- ``nutrients``: nutrientId -> name, EuroFIR component id and unit. Constituents are mapped by EuroFIR id.
- ``groups``: food groups with English names (hierarchical via parentId).
- ``sources`` (optional, https://www.matvaretabellen.no/api/en/sources.json): describes each sourceId;
  when given, values record their source (e.g. "USDA ... Release 28") instead of the bare id.

Definitions checked against the data:

- Energy (kJ and kcal) is calculated with the EU Regulation 1169/2011 factors; kcal is used as published.
- "Karbo" (EuroFIR CHO) is available carbohydrate (sugar + starch), so ours adds dietary fibre (FIBT).
- "Vit A" is RAE (retinol + beta-carotene/12); "Vit A RE" (factor 1/6) is not mapped.
- "Vit E" is alpha-tocopherol equivalents (unit mg-ATE) and is not mapped.
- "Folat" is total folate, used as DFE with that caveat (the table doesn't report added folic acid). It is
  skipped for food supplements and for foods whose name says folate/B-vitamins were added: that is folic
  acid, which counts 1.7x as DFE.
- "Niacin" is preformed niacin (NIA); niacin equivalents (NIAEQ) are not mapped.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food

DATASET = BY_KEY["intl_matvaretabellen"]
DERIVATION = "Matvaretabellen"
MAX_DERIVATION = 120  # FoodNutrient.derivation column length

# EuroFIR component id -> our nutrient code or Components special key.
MAPPING: dict[str, str] = {
    "WATER": "water_g", "PROT": "protein_g", "FAT": "fat_g", "FASAT": "sat_fat_g", "FAMS": "mono_fat_g",
    "FAPU": "poly_fat_g", "FATRS": "trans_fat_g", "CHORL": "cholesterol_mg", "CHO": "available_carbs_g",
    "FIBT": "fiber_g", "SUGAR": "sugars_g", "SUGAD": "added_sugars_g", "ALC": "alcohol_g",
    "RETOL": "retinol_ug", "CARTB": "beta_carotene_ug", "VITD": "vitamin_d_ug", "VITK1": "vitamin_k_ug",
    "THIA": "thiamin_mg", "RIBF": "riboflavin_mg", "NIA": "niacin_mg", "VITB6": "vitamin_b6_mg",
    "FOL": "folate_ug_dfe", "VITB12": "vitamin_b12_ug", "VITC": "vitamin_c_mg", "BIOT": "biotin_ug",
    "CHOLN": "choline_mg", "CA": "calcium_mg", "FE": "iron_mg", "NA": "sodium_mg", "K": "potassium_mg",
    "MG": "magnesium_mg", "P": "phosphorus_mg", "ZN": "zinc_mg", "CU": "copper_mg", "SE": "selenium_ug",
    "ID": "iodine_ug",
}
VITAMIN_A_RAE = "VITA"  # mapped only when its unit says RAE
SPECIAL_UNITS = {"available_carbs_g": "g", "retinol_ug": "µg", "beta_carotene_ug": "µg"}
NOTES = {"folate_ug_dfe": "total folate as DFE (no folic acid assumed)"}
FOLIC_ACID_ADDED = re.compile(r"folat|folic|multi ?vitamin|b-vitamins|liquid vitamins", re.IGNORECASE)


def _load(path: Path, key: str) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))[key]


def _source_note(source_id: str | None, sources: dict[str, str], budget: int) -> str | None:
    """'source 460g: US Department of Agriculture, …' cut to ``budget`` characters."""
    if not source_id:
        return None
    note = f"source {source_id}"
    desc = sources.get(source_id)
    if desc:
        desc = re.sub(r"\s+", " ", desc.split("   (")[0]).strip().rstrip(".")
        note = f"{note}: {desc}"
    return note if len(note) <= budget else note[: budget - 1].rstrip() + "…"


def _group_names(group_id: str | None, groups: dict[str, dict]) -> list[str]:
    """English names of the food's group and its parents, most specific first."""
    names, seen = [], set()
    group = groups.get(group_id or "")
    while group and group["foodGroupId"] not in seen:
        seen.add(group["foodGroupId"])
        names.append(group.get("name") or "")
        group = groups.get(group.get("parentId") or "")
    return names


def _portions(food: dict) -> list[tuple[str, float]]:
    out = []
    for p in food.get("portions") or []:
        name, grams = (p.get("portionName") or "").strip(), p.get("quantity")
        if not name or not grams or (p.get("unit") or "").lower() != "g":
            continue
        name = re.sub(r"^pcs\b", "piece", name)
        out.append((name if name.startswith("for ") else f"1 {name}", float(grams)))
    return out


def _food(food: dict, eurofir: dict[str, str], groups: dict[str, dict], sources: dict[str, str]) -> ExternalFood:
    comp = Components(DERIVATION)
    group_names = _group_names(food.get("foodGroupId"), groups)
    folic_acid = any("supplement" in name.lower() for name in group_names) or bool(FOLIC_ACID_ADDED.search(food["foodName"]))

    def add(key: str, item: dict, unit: str | None) -> None:
        extra = NOTES.get(key)
        budget = MAX_DERIVATION - len(DERIVATION) - 2 - (len(extra) + 2 if extra else 0)
        note = "; ".join(x for x in (extra, _source_note(item.get("sourceId"), sources, budget)) if x)
        comp.add(key, item.get("quantity"), unit, note=note or None)

    calories, energy = food.get("calories") or {}, food.get("energy") or {}
    if (calories.get("unit") or "").lower() == "kcal":
        add("energy_kcal", calories, "kcal")
    if (energy.get("unit") or "").lower() == "kj":
        add("energy_kj", energy, None)
    for item in food.get("constituents") or []:
        component, unit = eurofir.get(item.get("nutrientId"), item.get("nutrientId")), item.get("unit")
        if unit is None:
            continue  # no quantity: not known
        if component == VITAMIN_A_RAE:
            if unit.upper() == "RAE":
                add("vitamin_a_ug", item, "µg RAE")
            continue
        key = MAPPING.get(component)
        if key is None or (key in SPECIAL_UNITS and unit != SPECIAL_UNITS[key]):
            continue
        if key == "folate_ug_dfe" and folic_acid:
            continue
        add(key, item, unit)

    food_id = food["foodId"]
    return make_food(source=DATASET.source, source_id=food_id, name=food["foodName"], data_type="Matvaretabellen",
                     citation=f"{DATASET.attribution.rstrip('.')}. Food {food_id}.", components=comp,
                     category=group_names[-1] if group_names else None, source_url=food.get("uri"),
                     portions=_portions(food))


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    eurofir = {n["nutrientId"]: n.get("euroFirId") or n["nutrientId"] for n in _load(files["nutrients"], "nutrients")}
    groups = {g["foodGroupId"]: g for g in _load(files["groups"], "foodGroups")}
    sources = {s["sourceId"]: s.get("description") or "" for s in _load(files["sources"], "sources")} \
        if files.get("sources") else {}
    for food in _load(files["foods"], "foods"):
        if not food.get("foodId") or not food.get("foodName"):
            continue
        parsed = _food(food, eurofir, groups, sources)
        if parsed.nutrients:
            yield parsed
