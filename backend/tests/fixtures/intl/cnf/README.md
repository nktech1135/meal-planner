Excerpt of the Canadian Nutrient File 2026, used by `tests/test_intl_afcd_cnf.py`.

Source: Contains information licensed under the Open Government Licence – Canada
(https://open.canada.ca/en/open-government-licence-canada). Health Canada, Canadian Nutrient File 2026.
https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109

`cnf_excerpt.zip` was trimmed on 2026-10-30 from `cnf_fcen_all-files-data_2026.zip`, keeping the CSV
encoding (UTF-8 with BOM) and dropping the PDFs. Rows are unchanged:

- `Nutrient_Name.csv`, `Nutrient_Source.csv`, `Food_Source.csv`, `CNF_Food_Group.csv`, `Measure_Type.csv`: complete.
- `Food_Name.csv`, `Nutrient_Amount.csv`, `Measure_Weight_Conversion.csv`: only foods 1696 (apple), 113 (whole milk),
  4066 (white bread), 3241 (eulachon; no DFE value), 4516 (whole-wheat pasta; no RAE value), 1260 (bran cereal;
  folic acid but no DFE value) and 5 (chow mein; copied unchanged from USDA, so the parser skips it).
- `Measure_Name.csv`: only the measures those foods use.
