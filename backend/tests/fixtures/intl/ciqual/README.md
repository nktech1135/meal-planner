Excerpts of the French food composition table Ciqual 2025 (XML), used by `tests/test_intl_ciqual_norway.py`.

Source: Anses. 2025. Table de composition nutritionnelle des aliments Ciqual. https://doi.org/10.57745/RDMHWY
Licence: Etalab Open Licence 2.0 (https://www.etalab.gouv.fr/licence-ouverte-open-licence/).

Trimmed on 2026-10-30 from the published files, keeping their encoding (UTF-8 with BOM, CRLF) and
formatting; the rows themselves are unchanged:

- `alim.xml` (datafile 666252): foods 1032, 2002, 9811, 13039 and 19024.
- `compo.xml` (datafile 666249): those foods' rows for the constituents in `const.xml`.
- `const.xml` (datafile 666246): the constituents the parser maps plus a few it deliberately ignores
  (51104 vitamin A activity, 53100 vitamin E, 333 Jones-factor energy, 25003 crude protein).
- `groups.xml` (datafile 666250): one row for each of those foods' food groups.
