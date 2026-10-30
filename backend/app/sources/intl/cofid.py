"""UK Composition of Foods Integrated Dataset (CoFID 2021, Public Health England).

One workbook; each nutrient sheet has three header rows (label with unit, component code,
long name) and the same foods in the same order (columns A–G: food code, name, description,
group, previous code, references, footnote). Values are per 100 g edible portion, except
alcoholic beverages, which are per 100 ml. "Tr" = trace, "N" = present but unknown (missing),
blank = not measured.

Definition notes (from the CoFID 2021 user guide):

- Carbohydrate (CHO) is *available* carbohydrate expressed as monosaccharide equivalents. It is
  converted to actual weight with the guide's factors (starch ÷ 1.10, glucose/fructose/galactose
  as given, the rest ÷ 1.05) and total carbohydrate is that weight plus AOAC fibre. NSP
  (Englyst) fibre is a narrower measure and is not used as dietary fibre, so foods without
  AOAC fibre get no fibre or total carbohydrate.
- Total sugars are monosaccharide equivalents too: converted to weight when the individual
  sugars are given (disaccharides ÷ 1.05), otherwise kept as published and noted.
- Thiamin, vitamin B6 and pantothenate follow CoFID's conventions (thiamine chloride
  hydrochloride, pyridoxine hydrochloride, calcium pantothenate) and are mapped as published.
- Total folate is mapped as DFE with that caveat, except for foods described as fortified and
  infant formulas, where added folic acid makes total folate understate DFE.
- Carotene (CAREQU) is beta-carotene equivalents (beta-carotene + ½ alpha-carotene +
  ½ cryptoxanthins), so retinol + CAREQU/12 is exactly RAE. Retinol equivalents (RETEQU) and
  vitamin E as alpha-tocopherol equivalents (VITE) are not mapped; alpha-tocopherol comes from
  the vitamin fractions sheet where analysed.
- Vitamin D for meat, poultry and eggs adds 5 × 25-hydroxy vitamin D3; for those foods only
  cholecalciferol (from the fractions sheet) is used.
- Niacin (NIAC) is preformed niacin; niacin equivalents are not mapped.
"""

import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import openpyxl

from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value, unit_in

DATASET = BY_KEY["intl_cofid"]
DATA_TYPE = "CoFID 2021"
SHEETS = ("1.2 Factors", "1.3 Proximates", "1.4 Inorganics", "1.5 Vitamins", "1.6 Vitamin Fractions")

# CoFID component code -> (our nutrient code or Components special key, note on the value).
DIRECT = {
    "WATER": ("water_g", None),
    "PROT": ("protein_g", None),
    "FAT": ("fat_g", None),
    "KCALS": ("energy_kcal", None),
    "KJ": ("energy_kj", None),
    "AOACFIB": ("fiber_g", "AOAC fibre"),
    "ALCO": ("alcohol_g", None),
    "SATFOD": ("sat_fat_g", None),
    "MONOFOD": ("mono_fat_g", None),
    "POLYFOD": ("poly_fat_g", None),
    "FODTRANS": ("trans_fat_g", None),
    "CHOL": ("cholesterol_mg", None),
    "NA": ("sodium_mg", None),
    "K": ("potassium_mg", None),
    "CA": ("calcium_mg", None),
    "MG": ("magnesium_mg", None),
    "P": ("phosphorus_mg", None),
    "FE": ("iron_mg", None),
    "CU": ("copper_mg", None),
    "ZN": ("zinc_mg", None),
    "MN": ("manganese_mg", None),
    "SE": ("selenium_ug", None),
    "I": ("iodine_ug", None),
    "RET": ("retinol_ug", None),
    "CAREQU": ("beta_carotene_ug", None),
    "ATOPH": ("vitamin_e_mg", None),
    "VITK1": ("vitamin_k_ug", None),
    "THIA": ("thiamin_mg", None),
    "RIBO": ("riboflavin_mg", None),
    "NIAC": ("niacin_mg", "preformed niacin"),
    "VITB6": ("vitamin_b6_mg", None),
    "VITB12": ("vitamin_b12_ug", None),
    "PANTO": ("pantothenic_mg", None),
    "BIOT": ("biotin_ug", None),
    "VITC": ("vitamin_c_mg", None),
}
FOLATE_NOTE = "total folate; equals DFE only without added folic acid"
FORTIFIED = re.compile(r"\bfortified\b", re.I)

# Appendix B of the CoFID 2021 user guide: food group and sub-group codes.
GROUPS = {
    "A": "Cereals and cereal products", "AA": "Flours, grains and starches", "AB": "Sandwiches", "AC": "Rice",
    "AD": "Pasta", "AE": "Pizzas", "AF": "Breads", "AG": "Rolls", "AI": "Breakfast cereals",
    "AK": "Infant cereal foods", "AM": "Biscuits", "AN": "Cakes", "AO": "Pastry", "AP": "Buns and pastries",
    "AS": "Puddings", "AT": "Savouries",
    "B": "Milk and milk products", "BA": "Cows milk", "BAB": "Breakfast milk", "BAE": "Skimmed milk",
    "BAH": "Semi-skimmed milk", "BAK": "Whole milk", "BAN": "Channel Island milk", "BAR": "Processed milks",
    "BC": "Other milks", "BF": "Infant formulas", "BFD": "Whey-based modified milks",
    "BFG": "Non-whey-based modified milks", "BFJ": "Soya-based modified milks", "BFP": "Follow-on formulas",
    "BH": "Milk-based drinks", "BJ": "Creams", "BJC": "Fresh creams (pasteurised)",
    "BJF": "Frozen creams (pasteurised)", "BJL": "Sterilised creams", "BJP": "UHT creams", "BJS": "Imitation creams",
    "BL": "Cheeses", "BN": "Yogurts", "BNE": "Whole milk yogurts", "BNH": "Low fat yogurts", "BNS": "Other yogurts",
    "BP": "Ice creams", "BR": "Puddings and chilled desserts", "BV": "Savoury dishes and sauces",
    "C": "Eggs", "CA": "Eggs", "CD": "Egg dishes", "CDE": "Savoury egg dishes", "CDH": "Sweet egg dishes",
    "D": "Vegetables", "DA": "Potatoes", "DAE": "Early potatoes", "DAM": "Main crop potatoes",
    "DAP": "Chipped old potatoes", "DAR": "Potato products", "DB": "Beans and lentils", "DF": "Peas",
    "DG": "Vegetables, general", "DI": "Vegetables, dried", "DR": "Vegetable dishes",
    "F": "Fruit", "FA": "Fruit, general", "FC": "Fruit juices",
    "G": "Nuts and seeds", "GA": "Nuts and seeds, general",
    "H": "Herbs and spices",
    "J": "Fish and fish products", "JA": "White fish", "JC": "Fatty fish", "JK": "Crustacea", "JM": "Molluscs",
    "JR": "Fish products and dishes",
    "M": "Meat and meat products", "MA": "Meat", "MAA": "Bacon", "MAC": "Beef", "MAE": "Lamb", "MAG": "Pork",
    "MAI": "Veal", "MC": "Poultry", "MCA": "Chicken", "MCC": "Duck", "MCE": "Goose", "MCG": "Grouse",
    "MCI": "Partridge", "MCK": "Pheasant", "MCM": "Pigeon", "MCO": "Turkey", "ME": "Game", "MEA": "Hare",
    "MEC": "Rabbit", "MEE": "Venison", "MG": "Offal", "MBG": "Burgers and grillsteaks", "MI": "Meat products",
    "MIG": "Other meat products", "MR": "Meat dishes",
    "O": "Fats and oils", "OA": "Spreading fats", "OB": "Animal fats", "OC": "Oils", "OE": "Non-animal fats",
    "OF": "Cooking fats",
    "P": "Beverages", "PA": "Powdered drinks, essences and infusions", "PAA": "Powdered drinks and essences",
    "PAC": "Infusions", "PC": "Soft drinks", "PCA": "Carbonated drinks", "PCC": "Squash and cordials", "PE": "Juices",
    "Q": "Alcoholic beverages", "QA": "Beers", "QC": "Ciders", "QE": "Wines", "QF": "Fortified wines",
    "QG": "Vermouths", "QI": "Liqueurs", "QK": "Spirits",
    "S": "Sugars, preserves and snacks", "SC": "Sugars, syrups and preserves", "SE": "Confectionery",
    "SEA": "Chocolate confectionery", "SEC": "Non-chocolate confectionery", "SN": "Savoury snacks",
    "SNA": "Potato-based snacks", "SNB": "Potato and mixed cereal snacks", "SNC": "Non-potato snacks",
    "W": "Soups, sauces and miscellaneous foods", "WA": "Soups", "WAA": "Homemade soups", "WAC": "Canned soups",
    "WAE": "Packet soups", "WC": "Sauces", "WCD": "Dairy sauces", "WCG": "Salad sauces, dressings and pickles",
    "WCN": "Non-salad sauces", "WE": "Pickles and chutneys", "WY": "Miscellaneous foods",
}


def category(group: str | None) -> str | None:
    """'DAM' -> 'Vegetables: Main crop potatoes' (longest known sub-group under its main group)."""
    group = (group or "").strip().upper()
    if not group or group[0] not in GROUPS:
        return None
    main = GROUPS[group[0]]
    sub = next((GROUPS[group[:n]] for n in range(len(group), 1, -1) if group[:n] in GROUPS), None)
    return f"{main}: {sub}" if sub and sub != main else main


def _read_sheets(path: Path) -> tuple[dict[str, tuple[str | None, str]], list[dict]]:
    """Return ({component code: (unit, sheet)}, [one dict per food row merged across sheets])."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        units: dict[str, tuple[str | None, str]] = {}
        foods: dict[tuple[str, int], dict] = {}
        order: list[tuple[str, int]] = []
        for name in SHEETS:
            rows = wb[name].iter_rows(values_only=True)
            labels, codes, _ = next(rows), next(rows), next(rows)
            keys = [(str(c).strip() if c else str(lbl or "").strip()) for c, lbl in zip(codes, labels, strict=False)]
            for i in range(7, len(keys)):
                if keys[i]:
                    units.setdefault(keys[i], (unit_in(str(labels[i] or "")), name))
            seen: Counter[str] = Counter()
            for row in rows:
                code = str(row[0]).strip() if row and row[0] is not None else ""
                if not code:
                    continue
                seen[code] += 1  # CoFID 2021 has one code used for two foods: keep them apart by occurrence
                key = (code, seen[code])
                if key not in foods:
                    foods[key] = {"_code": code, "_n": seen[code], "_name": row[1], "_desc": row[2], "_group": row[3]}
                    order.append(key)
                food = foods[key]
                for i in range(7, min(len(keys), len(row))):
                    if keys[i] and row[i] is not None:
                        food.setdefault(keys[i], row[i])
        return units, [foods[k] for k in order]
    finally:
        wb.close()


def _num(food: dict, code: str) -> float | None:
    return parse_value(food.get(code))[0]


def _carbs_as_weight(food: dict) -> float | None:
    """Available carbohydrate converted from monosaccharide equivalents to weight (CoFID guide factors)."""
    cho = _num(food, "CHO")
    if cho is None:
        return None
    starch = _num(food, "STAR")
    if starch is None:
        return cho / 1.05
    mono = [_num(food, c) for c in ("GLUC", "GALACT", "FRUCT")]
    if None in mono:
        return starch / 1.10 + max(cho - starch, 0) / 1.05
    return starch / 1.10 + sum(mono) + max(cho - starch - sum(mono), 0) / 1.05  # rest: di- and oligosaccharides


def _sugars_as_weight(food: dict) -> tuple[float, str] | None:
    mono = [_num(food, c) for c in ("GLUC", "GALACT", "FRUCT")]
    di = [_num(food, c) for c in ("SUCR", "MALT", "LACT")]
    if None not in mono and None not in di:
        return sum(mono) + sum(di) / 1.05, "as weight"
    total = _num(food, "TOTSUG")
    return (total, "monosaccharide equivalents") if total is not None else None


def _food(food: dict, units: dict[str, tuple[str | None, str]]) -> ExternalFood | None:
    code, name, group = food["_code"], str(food["_name"] or "").strip(), str(food["_group"] or "").strip()
    if not name:
        return None
    base = DATA_TYPE
    scale = 1.0
    if group.upper().startswith("Q"):  # alcoholic beverages are published per 100 ml
        gravity = _num(food, "Specific gravity")
        if gravity:
            scale, base = 1 / gravity, f"{DATA_TYPE}; per 100 ml / specific gravity {gravity:g}"
        else:
            base = f"{DATA_TYPE}; published per 100 ml"
    comps = Components(base)

    def add(key: str, raw, unit: str | None, note: str | None = None) -> None:
        value, flag = parse_value(raw)
        if value is not None:
            comps.add(key, value * scale, unit, "; ".join(x for x in (note, flag) if x) or None)

    for source_code, (key, note) in DIRECT.items():
        if source_code in food:
            add(key, food[source_code], units[source_code][0], note)

    # Vitamin D: CoFID adds 5 x 25-hydroxy D3 (meat, poultry, eggs); ours is D2 + D3 only.
    if (_num(food, "25OHD3") or 0) > 0:
        if "VITD3" in food:
            add("vitamin_d_ug", food["VITD3"], units["VITD3"][0], "cholecalciferol only (excludes 25-OH D3)")
    elif "VITD" in food:
        add("vitamin_d_ug", food["VITD"], units["VITD"][0])

    text = f"{name} {food['_desc'] or ''}"
    if "FOLT" in food and not FORTIFIED.search(text) and not group.upper().startswith("BF"):
        add("folate_ug_dfe", food["FOLT"], units["FOLT"][0], FOLATE_NOTE)

    sugars = _sugars_as_weight(food)
    if sugars is not None:
        add("sugars_g", sugars[0], "g", sugars[1])
    carbs, fibre = _carbs_as_weight(food), parse_value(food.get("AOACFIB"))[0]
    if carbs is not None and fibre is not None:
        add("carbs_g", carbs + fibre, "g", "available carbohydrate (as weight) + AOAC fibre")

    return make_food(
        source=DATASET.source, source_id=code if food["_n"] == 1 else f"{code}#{food['_n']}", name=name,
        data_type=DATA_TYPE, category=category(group), citation=f"{DATASET.attribution.rstrip('.')}. Food {code}.",
        components=comps,
    )


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    units, foods = _read_sheets(files["data"])
    for food in foods:
        ext = _food(food, units)
        if ext is not None:
            yield ext
