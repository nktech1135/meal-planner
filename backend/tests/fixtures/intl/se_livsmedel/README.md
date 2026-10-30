Excerpt of the Swedish Food Agency's food database (Livsmedelsdatabasen), used by `tests/test_intl_se_fi.py`.

Source: The Swedish Food Agency food database (Livsmedelsverket), version 2026-07-01.
Licence: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/; "Tillhandahålls enligt CC BY", the Swedish Food
Agency is to be named as the source).

`livsmedel_excerpt.json` has the shape `app.sources.intl.se_livsmedel.fetch_all` assembles, made on 2026-10-30
from https://dataportal.livsmedelsverket.se/livsmedel/api/v1 (`/livsmedel?sprak=2` and
`/livsmedel/{nummer}/naringsvarden?sprak=2`, English) and the English Excel export of the search site
(https://soknaringsinnehall.livsmedelsverket.se, for "version" and the food groups). Records are unchanged except
that nutrient values keep only the fields the parser reads (`VALUE_FIELDS`). Foods: 588 (apple), 123 (milk 3%
fortified), 2515 (rice boiled), 706 (corn flakes, fortified), 257 (potato gratin, a calculated dish), 1 (beef tallow;
below detection limit), 347 (frozen corn; below quantification limit), 164 (crisp bread; an "Unknown" value), 31
(butter; trace) and 1881 (energy bar; vitamin A with the RE factor 1/6).
