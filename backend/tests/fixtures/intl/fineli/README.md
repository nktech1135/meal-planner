Excerpt of the Fineli open-data package (Basic package 2, 74 components, Release 20), used by
`tests/test_intl_se_fi.py`.

Source: Finnish Institute for Health and Welfare, Fineli. Licence: CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). "Fineli" is a registered trademark of THL.
Full package: `app/data/fineli/fineli_rel20_74_components.zip` (see the README there).

`fineli_rel20_excerpt.zip` was trimmed on 2026-10-30, keeping the CSV format (semicolons, Latin-1, CRLF, decimal
commas); rows are unchanged:

- `food.csv`, `foodname_EN.csv`, `component_value.csv`, `foodaddunit.csv`, `contribfood.csv`: only foods 11060
  (apple, domestic, without skin), 689 (milk, 3.5% fat), 1370 (rice, boiled without salt; a recipe), 1009 (rye
  bread; process "baked"), 606 (skimmed milk; vitamin D including 25-hydroxy-D3), 29071 (chocolate milk; a recipe
  made with 606) and 163 (corn flakes; a breakfast cereal with added folic acid).
- `component.csv`, `descript.txt` and the English thesaurus files the parser reads: complete.
