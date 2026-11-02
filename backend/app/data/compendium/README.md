# 2024 Adult Compendium of Physical Activities (vendored)

`adult_2024.json` lists the 1,111 activities in the official 2024 Adult Compendium PDF, one per line as
`[activity code, MET value, major heading, activity description]`. The values are unchanged from the PDF.
The Compendium team asks users not to change MET values or combine activities with different MET levels.

- Source PDF: https://pacompendium.com/wp-content/uploads/2025/02/1_2024-adult-compendium_1_2024.pdf
  (linked from https://pacompendium.com/adult-compendium/), retrieved 2026-11-02.
  SHA-256 `ac30234b8f8f813837e282773cfcb3e0fe062334777c2f7b3213429c4fbc251c` (563,091 bytes, 28 pages).
- Citation: Herrmann SD, Willis EA, Ainsworth BE, et al. 2024 Adult Compendium of Physical Activities: A third
  update of the energy costs of human activities. J Sport Health Sci. 2024;13(1):6-12.
  doi:10.1016/j.jshs.2023.10.010 (PMID 38242596).
- The article is open access under CC BY-NC-ND 4.0. The Compendium website gives no separate licence and asks
  that the website or the publication be cited. The paper reports 1,114 activities; the PDF table has 1,111.
- 1 MET is a standardised resting metabolic rate of 3.5 mL O2/kg/min, about 1.0 kcal/kg/h. The Compendium
  is a starting point and does not give precise individual energy expenditure.

Rebuilt by `extract.py` (see its docstring). Read by `app/services/exercise.py`.
