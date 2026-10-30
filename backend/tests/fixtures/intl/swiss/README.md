# Swiss Food Composition Database V 7.1 excerpt

`swiss_fcdb71_excerpt.xlsx` is a trimmed copy of `Swiss_food_composition_database.xlsx`
(https://naehrwertdaten.ch/wp-content/uploads/2026/07/Swiss_food_composition_database.xlsx,
downloaded 2026-10-30), used by `tests/test_intl_dk_swiss.py`. Rows are copied unchanged:

- `Generic Foods`: the title, blank and header rows, and foods 10533 (agar agar: "n.d." values),
  273 (almond: "<0.5"), 378 (apple, fresh), 290 (egg, raw: "tr."), 14130 (oat drink fortified with
  calcium and vitamins), 1066 (rice, cooked) and 62 (whole milk, pasteurized).
- `Branded foods`: the title, blank and header rows, and food 524 (mineral water, Perrier).
- `Sources`: the title, blank and header rows, and the references those foods' values cite.

The `Nutrient codes` sheet is not included.

Source: Swiss Food Composition Database V 7.1 (01.07.2026), Federal Food Safety and Veterinary
Office FSVO, www.naehrwertdaten.ch. The FSVO allows free use, including commercial use (e.g. in a
nutrition diary app), subject to acknowledgment of the source. The excerpt is a trimmed copy of the
original.
