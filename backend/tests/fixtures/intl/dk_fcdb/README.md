# Danish Food Composition Database 6.1 excerpt

`fcdb61_excerpt.xlsx` is a trimmed copy of `FCDB_6.1_Dataset.xlsx`
(https://ndownloader.figshare.com/files/65016537, DOI https://doi.org/10.11583/DTU.32312844,
downloaded 2026-10-30), used by `tests/test_intl_dk_swiss.py`. Rows are copied unchanged:

- `Data_Normalised`: the header and every row for foods 2 (apple, raw), 6 (whole milk, with
  25-hydroxy vitamin D), 174 (sweet biscuit: vitamin A only as RE), 251 (black olives: carbohydrate
  by difference below fibre, vitamin E only as alpha-TE), 263 (Rice Krispies, fortified) and
  1973 (rice, boiled).
- `Food`: those foods' rows (the first 14 columns; the rest of the published sheet is empty).
- `FoodGroup`, `Parameter`: complete.
- `Source`: the references those foods' values cite.

The `Readme` and `Data_Table` sheets are not included.

The Danish Food Composition Database (http://fcdb.fooddata.dk), version 6.1, May 2026, The Food
Institute, Technical University of Denmark. Licensed under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). The excerpt is a trimmed copy of the original.
