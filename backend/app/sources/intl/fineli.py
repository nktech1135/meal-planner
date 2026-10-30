"""Finnish food composition database Fineli (Finnish Institute for Health and Welfare, THL), open data
"Basic package 2" (4,232 foods, 74 components), Release 20 (August 2019).

File: ``zip``, the package as published (semicolon-separated CSV, Latin-1, CRLF, decimal commas):
component_value.csv (FOODID; EUFDNAME; BESTLOC; ACQTYPE; METHTYPE; METHIND), food.csv (FOODTYPE, PROCESS,
FUCLASS, ...), foodname_EN.csv, component.csv (units), foodaddunit.csv (portion grams), contribfood.csv
(recipe ingredients) and English thesaurus files. Values are per 100 g edible portion; a missing row or an
empty value is unknown. Fineli publishes no trace or below-limit markers.

Definitions checked against the data and the EuroFIR thesaurus names in the package:

- ENERC is energy in kJ only (EU labelling factors); kcal = kJ / 4.184.
- CHOCDF "carbohydrate, difference" (100 - water - protein - fat - ash - alcohol, or a recipe sum of such
  values) is our total carbohydrate. CHOAVL (available, sugars + starch) + FIBC is used only without CHOCDF.
- FIBC "fibre, total" is Fineli's published total fibre (enzymatic-gravimetric where analysed). FIBT is a
  sum of incomplete fibre fractions and is not used.
- VITA is RAE (retinol + beta-carotene/12 + other provitamin A carotenoids/24); used as published.
- VITE is alpha-tocopherol (XVITE, the TE form, isn't in the package).
- NIA is preformed niacin; NIAEQ (niacin equivalents) is not mapped.
- VITD is mapped except where Fineli computed it with 25-hydroxy-D3 (method MI0354) -- that is not D2 + D3 --
  including recipes that contain such an ingredient (contribfood.csv, transitively).
- FOL is total folate, used as DFE with that caveat except for foods likely to contain added folic acid:
  breakfast cereals, meal replacements, sport and baby foods, infant formulas, names that say vitamins were
  added or fortified, and recipes containing any of these.
- Not mapped: VITPYRID (vitamin B6 expressed as pyridoxine hydrochloride, not total B6), VITK (total vitamin
  K including menaquinones; ours is phylloquinone), FAMCIS (cis-monounsaturated fatty acids only), NACL
  (salt; sodium NA is mapped).
"""

import csv
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food

SOURCE = "fineli"
RELEASE = "Release 20"
DATA_TYPE = f"Fineli {RELEASE}"
ATTRIBUTION = ("Finnish Institute for Health and Welfare, Fineli. Finnish food composition database, Release 20 (2019). "
               "Licensed under CC BY 4.0.")
FOOD_URL = "https://fineli.fi/fineli/en/elintarvikkeet/{id}"
DERIVATION = "Fineli"
MAX_DERIVATION = 120

# EuroFIR component -> our nutrient code or Components special key.
MAPPING: dict[str, str] = {
    "ENERC": "energy_kj", "PROT": "protein_g", "FAT": "fat_g", "CHOCDF": "carbs_g", "CHOAVL": "available_carbs_g",
    "FIBC": "fiber_g", "SUGAR": "sugars_g", "FASAT": "sat_fat_g", "FAPU": "poly_fat_g", "FATRN": "trans_fat_g",
    "CHOLE": "cholesterol_mg", "WATER": "water_g", "ALC": "alcohol_g",
    "NA": "sodium_mg", "K": "potassium_mg", "CA": "calcium_mg", "FE": "iron_mg", "MG": "magnesium_mg",
    "P": "phosphorus_mg", "ZN": "zinc_mg", "CU": "copper_mg", "MN": "manganese_mg", "SE": "selenium_ug",
    "ID": "iodine_ug", "VITA": "vitamin_a_ug", "VITD": "vitamin_d_ug", "VITE": "vitamin_e_mg",
    "VITC": "vitamin_c_mg", "THIA": "thiamin_mg", "RIBF": "riboflavin_mg", "NIA": "niacin_mg",
    "VITB12": "vitamin_b12_ug", "FOL": "folate_ug_dfe",
}
UNITS = {"G": "g", "MG": "mg", "UG": "µg", "KJ": "kJ"}
VITAMIN_D_WITH_25OHD = "MI0354"  # "Vitamin D activity calculated from cholecalciferol, ergocalciferol and 25-OH-D3"
FOLATE_CAVEAT = "total folate as DFE (no folic acid assumed)"
FOLIC_ACID_CLASSES = {"CERBRKF", "MEALREP", "SPORTFOO", "SPECSUPP", "INFMILK"}  # FUCLASS
FOLIC_ACID_PARENTS = {"SPECTOT", "BABYFTOT", "MMILK"}  # FUCLASSP
FOLIC_ACID_NAME = re.compile(r"VITAMINS|MULTIVITAMIN|FORTIFIED|ENRICHED|FOLIC|FOLATE|VITAMIN B\b|ADDED VITAMIN AND")
# PROCESS -> (state, cooking method), used when the name doesn't say.
PROCESS_STATE = {"RAW": ("raw", None), "BOIL": ("cooked", "boiled"), "BOILDR": ("cooked", "boiled"),
                 "BAK": ("cooked", "baked"), "FRIE": ("cooked", "fried"), "GRIL": ("cooked", "grilled"),
                 "ROAS": ("cooked", "roasted")}
PORTIONS = {"KPL_S": "1 piece (small)", "KPL_M": "1 piece (medium)", "KPL_L": "1 piece (large)",
            "KPL_VALM": "1 piece (as sold)", "PORTS": "1 portion (small)", "PORTM": "1 portion (medium)",
            "PORTL": "1 portion (large)", "DL": "1 decilitre", "RKL": "1 tablespoon", "TL": "1 teaspoon"}
ARCHIVED = "(ARC)"  # name prefix of foods kept for reference that are no longer on the market


def _member(zf: zipfile.ZipFile, name: str) -> str:
    for member in zf.namelist():
        if member.rsplit("/", 1)[-1].lower() == name.lower():
            return member
    raise ValueError(f"Fineli package has no {name} (has the format changed?)")


def _read(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(_member(zf, name)) as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";"):
            yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def _thesaurus(zf: zipfile.ZipFile, name: str) -> dict[str, str]:
    return {r["THSCODE"]: r["DESCRIPT"] for r in _read(zf, name)}


def _name(raw: str) -> str:
    """'APPLE, DOMESTIC, WITHOUT SKIN' -> 'Apple, domestic, without skin'."""
    text = raw.strip()
    archived = text.startswith(ARCHIVED)
    text = " ".join(text.removeprefix(ARCHIVED).lower().split())
    text = re.sub(r"\bvitamin ([a-z])\b", lambda m: f"vitamin {m.group(1).upper()}", text)
    text = re.sub(r"(\d) ?ug\b", r"\1 µg", text)
    text = text[:1].upper() + text[1:]
    return f"{text} (archived)" if archived else text


def _spread(seeds: set[str], recipes: dict[str, set[str]]) -> set[str]:
    """``seeds`` plus every recipe that contains one of them, directly or through other recipes."""
    users: dict[str, set[str]] = defaultdict(set)
    for recipe, ingredients in recipes.items():
        for ingredient in ingredients:
            users[ingredient].add(recipe)
    found, todo = set(seeds), list(seeds)
    while todo:
        for recipe in users.get(todo.pop(), ()):
            if recipe not in found:
                found.add(recipe)
                todo.append(recipe)
    return found


def _category(food: dict[str, str], classes: dict[str, str]) -> str | None:
    """The specific food-use class ('Fruits', 'Milks >2% fat'), else its parent; withdrawn classes are skipped."""
    for code in (food.get("FUCLASS"), food.get("FUCLASSP")):
        name = classes.get(code or "", "").strip()
        if name and not name.startswith("POISTETTU_"):
            return name
    return None


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    with zipfile.ZipFile(files["zip"]) as zf:
        units = {r["EUFDNAME"]: UNITS.get(r["COMPUNIT"].upper()) for r in _read(zf, "component.csv")}
        names = {r["FOODID"]: r["FOODNAME"] for r in _read(zf, "foodname_EN.csv")}
        classes = _thesaurus(zf, "fuclass_EN.csv")
        methods = _thesaurus(zf, "methtype_EN.csv")
        foods = list(_read(zf, "food.csv"))
        recipes: dict[str, set[str]] = defaultdict(set)
        for r in _read(zf, "contribfood.csv"):
            recipes[r["FOODID"]].add(r["CONFDID"])
        values: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in _read(zf, "component_value.csv"):
            if r["EUFDNAME"] in MAPPING:
                values[r["FOODID"]].append(r)
        portions: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for r in _read(zf, "foodaddunit.csv"):
            label = PORTIONS.get(r["FOODUNIT"])
            grams = float(r["MASS"].replace(",", ".") or 0)
            if label and grams > 0:
                portions[r["FOODID"]].append((label, grams))

    vitamin_d_25ohd = _spread({fid for fid, rows in values.items()
                               if any(r["EUFDNAME"] == "VITD" and r["METHIND"] == VITAMIN_D_WITH_25OHD for r in rows)},
                              recipes)
    folic_acid = _spread({f["FOODID"] for f in foods if f.get("FUCLASS") in FOLIC_ACID_CLASSES
                          or f.get("FUCLASSP") in FOLIC_ACID_PARENTS or f.get("FOODTYPE") == "SUPPLE"
                          or FOLIC_ACID_NAME.search(names.get(f["FOODID"], f.get("FOODNAME", "")).upper())},
                         recipes)

    for food in foods:
        fid = food["FOODID"]
        raw_name = names.get(fid) or food.get("FOODNAME")
        rows = values.get(fid)
        if not raw_name or not rows:
            continue
        comp = Components(DERIVATION)
        for r in sorted(rows, key=lambda r: r["EUFDNAME"] != "CHOCDF"):  # CHOCDF before the CHOAVL fallback
            key, component = MAPPING[r["EUFDNAME"]], r["EUFDNAME"]
            if (key == "vitamin_d_ug" and fid in vitamin_d_25ohd) or (key == "folate_ug_dfe" and fid in folic_acid):
                continue
            unit = units.get(component)
            if unit is None:
                continue
            extra = FOLATE_CAVEAT if key == "folate_ug_dfe" else None
            method = methods.get(r["METHTYPE"])
            budget = MAX_DERIVATION - len(DERIVATION) - 2 - (len(extra) + 2 if extra else 0)
            note = "; ".join(x for x in (extra, method[:budget] if method else None) if x)
            comp.add(key, r["BESTLOC"], None if key in Components.SPECIAL else unit, note=note or None)
        if "carbs_g" in comp.values:
            comp.values.pop("available_carbs_g", None)
        parsed = make_food(source=SOURCE, source_id=fid, name=_name(raw_name), data_type=DATA_TYPE,
                           citation=f"{ATTRIBUTION.rstrip('.')}. Food {fid}.", components=comp,
                           category=_category(food, classes), source_url=FOOD_URL.format(id=fid),
                           portions=portions.get(fid, []))
        if parsed.state is None and food.get("PROCESS") in PROCESS_STATE:
            parsed.state, parsed.cooking_method = PROCESS_STATE[food["PROCESS"]]
        if parsed.nutrients:
            yield parsed
