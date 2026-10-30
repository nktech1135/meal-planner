"""Canadian Nutrient File (CNF) 2026, Health Canada.

File: ``zip``, the "all files" CSV download (UTF-8 with BOM). Values are per 100 g of edible
portion. CNF nutrient codes are USDA SR nutrient numbers with the same definitions (checked
against Nutrient_Name.csv tagnames and the 2026 user guide), so they map through
``BY_FDC_NUMBER``: 208 kcal, 203 protein, 204 fat, 205 carbohydrate by difference, 291 total
dietary fibre, 269 total sugars, 320 RAE, 328 vitamin D (D2 + D3), 323 alpha-tocopherol,
430 phylloquinone, 435 DFE, 406 preformed niacin, and so on. Fallbacks, used only when the
preferred code is absent: 268 kJ for energy, 324 IU for vitamin D, 417 total folate for DFE
(with the caveat; skipped when folic acid 431 is above 0), retinol 319 + beta-carotene 321 for RAE.
Codes 851 and up are CNF-specific fatty acids and inulin; none matches a nutrient of ours.

Foods whose Food_Source_Code is 0 ("based on data from USDA: no changes") are skipped: they
are SR Legacy foods the USDA datasets already provide. Every other food is kept, including
USDA-based foods with Canadian changes and foods since deleted from USDA.

Each value's derivation carries CNF's per-nutrient source (Nutrient_Source.csv), e.g.
"CNF; Nutrient analyzed in a Canadian government lab" or "CNF; Nutrient value is an assumed
zero" (source code 12, kept as 0).
"""

import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from app.nutrients import BY_FDC_NUMBER
from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value

DATASET = BY_KEY["intl_cnf"]
DATA_TYPE = "CNF 2026"
USDA_UNCHANGED = {"0"}  # Food_Source_Code: "Food based on data from USDA: No changes"
TOTAL_FOLATE, FOLIC_ACID = "417", "431"
USER_MEASURE = "6"  # Measure_Type_Code: user-defined household measures (3 = refuse, 9 = yield)
UNITS = {"gram": "g", "milligram": "mg", "microgram": "µg", "kilocalorie": "kcal",
         "kilojoule": "kJ", "international unit": "IU"}
# Fallback codes -> (our code or Components special key, note). Added after the preferred codes,
# so they only fill a nutrient the food doesn't otherwise have.
FALLBACKS = {
    "268": ("energy_kj", None),
    "324": ("vitamin_d_ug", "converted from IU"),
    TOTAL_FOLATE: ("folate_ug_dfe", "total folate; equals DFE only for foods without added folic acid"),
    "319": ("retinol_ug", None),
    "321": ("beta_carotene_ug", None),
}


def _member(zf: zipfile.ZipFile, name: str) -> str:
    for member in zf.namelist():
        if member.rsplit("/", 1)[-1].lower() == name.lower():
            return member
    raise ValueError(f"CNF archive has no {name} (has the format changed?)")


def _sentence(text: str) -> str:
    """'Nutrient from canadian industry. Documentation incomplete.' without the final period or doubled spaces."""
    return " ".join(text.split()).rstrip(".")


def _read(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(_member(zf, name)) as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
            yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    with zipfile.ZipFile(files["zip"]) as zf:
        units = {r["Nutrient_Code"]: UNITS.get(r["Nutrient_Unit"].lower()) for r in _read(zf, "Nutrient_Name.csv")}
        wanted = {code for code, unit in units.items() if unit and (code in BY_FDC_NUMBER or code in FALLBACKS)}
        wanted.add(FOLIC_ACID)
        sources = {r["Nutrient_Source_Code"]: _sentence(r["Nutrient_Source_Description_EN"])
                   for r in _read(zf, "Nutrient_Source.csv")}
        groups = {r["CNF_Food_Group_Code"]: r["CNF_Food_Group_Description_EN"] for r in _read(zf, "CNF_Food_Group.csv")}
        measures = {r["Measure_Code"]: r["Measure_Description_and_Unit_EN"] for r in _read(zf, "Measure_Name.csv")}
        foods = [r for r in _read(zf, "Food_Name.csv") if r["Food_Source_Code"] not in USDA_UNCHANGED]
        kept = {r["Food_Code"] for r in foods}

        amounts: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for r in _read(zf, "Nutrient_Amount.csv"):
            if r["Food_Code"] in kept and r["Nutrient_Code"] in wanted:
                amounts[r["Food_Code"]].append((r["Nutrient_Code"], r["Nutrient_Amount"], r["Nutrient_Source_Code"]))

        portions: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for r in _read(zf, "Measure_Weight_Conversion.csv"):
            if r["Food_Code"] in kept and r["Measure_Type_Code"] == USER_MEASURE:
                grams, _ = parse_value(r["Measure_Weight_Conversion"])
                label = measures.get(r["Measure_Code"])
                if grams and label and (label, grams) not in portions[r["Food_Code"]]:
                    portions[r["Food_Code"]].append((label, grams))

    for food in foods:
        code = food["Food_Code"]
        comp = Components("CNF")
        rows = amounts.get(code, [])
        folic_acid = max((parse_value(amount)[0] or 0 for number, amount, _ in rows if number == FOLIC_ACID), default=0)
        # Preferred (catalog) codes first: Components keeps the first value for a key.
        for number, amount, source in sorted(rows, key=lambda row: row[0] in FALLBACKS):
            if number == FOLIC_ACID or (number == TOTAL_FOLATE and folic_acid > 0):
                continue  # total folate understates DFE when folic acid is added
            note = sources.get(source)
            if number in FALLBACKS:
                key, extra = FALLBACKS[number]
                note = "; ".join(x for x in (note, extra) if x)
            else:
                key = BY_FDC_NUMBER[number].code
            comp.add(key, amount, units.get(number), note)
        yield make_food(
            source=DATASET.source, source_id=code, name=food["Food_Description_EN"], data_type=DATA_TYPE,
            category=groups.get(food["CNF_Food_Group_Code"]), citation=f"{DATASET.attribution.rstrip('.')}. Food {code}.",
            components=comp, portions=portions.get(code, []),
        )
