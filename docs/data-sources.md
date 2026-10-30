# Data sources and trust levels

Every food, supplement, cooking yield and log entry carries a **trust level**.
Log entries and recipes take the *weakest* level of all the data that went into
them, so a dish made from USDA ingredients plus one hand-typed sauce is shown as
`user`. The daily summary breaks energy down by trust level, and the AI advisor is
told to say when its conclusions rest on weaker data.

| Level | Meaning | Examples |
|---|---|---|
| `analytical` | Government lab-analysed or compiled food composition data | USDA FDC Foundation, SR Legacy, FNDDS |
| `label` | Manufacturer label declarations, catalogued by a government database | USDA FDC Branded, NIH DSLD |
| `commercial` | Licensed commercial nutrition database | Nutritionix, Edamam |
| `user` | Entered by a user (manual foods, copies of imported foods, measured yields) | — |
| `unverified` | Crowdsourced; anyone can edit; not checked | Open Food Facts |

Label data deserves its own level. Labels may round values, and for supplements
the FDA does not check contents before sale, so a label is a manufacturer's claim
rather than a measurement.

Imported records are stored as shared, read-only foods along with the upstream
payload (`foods.source_payload`), citation and link. To change an imported food,
make a copy. The copy becomes `user` data and cites the original.

All keys and source switches below are set in the app (**Settings**, as an admin).

## Local USDA database (recommended)

**Settings → Data** imports USDA's public-domain datasets into the app's own
database. Search is then instant, works offline and isn't rate-limited:

| Dataset | Foods | Notes |
|---|---|---|
| SR Legacy (2018, final release) | ~7,800 | Raw and cooked forms of most basic foods |
| Foundation Foods (updated twice a year) | ~400 | The most detailed lab analyses |
| Survey foods / FNDDS | ~5,400 | Mixed dishes as eaten in the U.S. |
| Nutrient Retention Factors, Release 6 (2007) | 270 profiles | Vitamin/mineral losses by cooking method |
| Branded Foods (optional) | ~434,000 | U.S. packaged foods from manufacturer labels, with barcodes and ingredient lists |

The app checks FDC's download page for newer releases and offers **Update**.
Imports run in the background with progress shown, and only one runs at a time.
Re-importing replaces records in place, so log entries that refer to them keep
working. The retention CSV is pinned by SHA-256. 24 of its rows have no factor,
because the date was entered in the factor column; those rows are skipped rather
than guessed.

**Branded Foods** is large: about a 200 MB download (3.2 GB of JSON). Measured on
a laptop, it imported in under two minutes with about 440 MB peak memory and
took about 1 GB in SQLite. Values are manufacturer label data (trust: `label`).
Search ranks generic foods before branded products. On PostgreSQL, trigram
indexes (`pg_trgm`) keep searches fast at this size: a no-match search over
214,000 foods took 0.1 ms with the index and 65 ms without. SQLite installs
search the same data in about half a second.

## Barcodes

Every food picker has **Scan barcode**. It uses the browser's camera barcode
detector where available, and otherwise a lazily loaded decoder (ZXing) for
Safari and Firefox. Typing the digits always works. The camera needs HTTPS (or
localhost). A barcode is looked up in this order:

1. this app's database, including imported Branded Foods and products people
   have added;
2. USDA FoodData Central online (needs a USDA key in Settings);
3. Open Food Facts, but only if crowdsourced data is allowed, and flagged
   `unverified`.

Online finds are saved locally. Unknown products link to **Add it from the
label** with the barcode filled in, so they're found next time. UPC-A, EAN-13
and GTIN-14 forms of the same code all match.

## National databases outside the U.S.

Imported from **Settings → Data → Other countries**. Each is a free government
or research-institute database under an open licence. The files are pinned by
SHA-256 where the publisher issues fixed releases, so an upstream change fails
the import with an explanation rather than slipping in. Every food carries the
licence's required attribution in its citation, and all credits are listed on
the **Data sources & credits** page. People can hide databases from their own
searches in **Profile**.

| Database | Country | Licence |
|---|---|---|
| Australian Food Composition Database, Release 3 (FSANZ, 2025) | Australia | CC BY 4.0 |
| CoFID 2021 (McCance & Widdowson) | United Kingdom | Open Government Licence v3.0 |
| BLS 4.0 (Max Rubner-Institut, 2025) | Germany | CC BY 4.0 |
| Canadian Nutrient File 2026 (Health Canada); foods copied unchanged from USDA are skipped | Canada | Open Government Licence – Canada |
| Ciqual 2025 (ANSES) | France | Etalab Open Licence 2.0 |
| Matvaretabellen (Mattilsynet) | Norway | CC BY 4.0 |
| Danish Food Composition Database 6.1 (DTU Food Institute, 2026) | Denmark | CC BY 4.0 |
| Swiss Food Composition Database V 7.1 (FSVO, 2026); 30 branded items as label data | Switzerland | Free use incl. commercial, with acknowledgement |
| Livsmedelsdatabasen (Swedish Food Agency), assembled from its API in about 10 minutes, since no fetchable bulk file exists | Sweden | CC BY 4.0 |
| Fineli Release 20 (THL), the latest open-data release, shipped with the app because fineli.fi blocks automated downloads | Finland | CC BY 4.0 |

Not included, because their terms don't fit an app:
- **NEVO (Netherlands):** forbids modifying the data or charging users.
- **New Zealand FOODfiles:** the data must be shown unaltered.
- **Japan's Standard Tables:** Japanese names only, and paid distribution needs notice.
- **India's IFCT:** no open licence.

FSVO prescribes no exact acknowledgement wording; the app credits the database,
version, publisher and website. Fineli's live website has newer analyses than its
2019 open-data package; only the open release is licensed for reuse.

**Matching definitions.** National databases define some nutrients differently
from USDA. A value is only mapped when the definitions match, or when ours can be
derived from what's published:

| Our nutrient | When the database gives… | Then |
|---|---|---|
| Energy | kJ only | kcal = kJ ÷ 4.184 |
| Carbohydrate | available carbohydrate | add total dietary fibre to match USDA's total; not mapped without fibre |
| Vitamin A (RAE) | retinol + β-carotene | RAE = retinol + β-carotene ÷ 12; retinol *equivalents* (RE) are never mapped |
| Vitamin E | α-tocopherol *equivalents* (TE) | not mapped |
| Folate (DFE) | total folate | mapped, with the caveat that it equals DFE only when no folic acid is added |
| Any nutrient | trace or below the detection limit | stored as 0 with the reason recorded |
| Any nutrient | "not determined" | left out: unknown is not zero |

## Online sources

### USDA FoodData Central — free, enabled by default
- https://fdc.nal.usda.gov/ · API guide: https://fdc.nal.usda.gov/api-guide
- Public domain (CC0). Get a free API key at https://fdc.nal.usda.gov/api-key-signup
  and enter it in Settings. Without one, the shared `DEMO_KEY` is used, which is
  heavily rate-limited.
- Values are per 100 g. Portions (household measures with gram weights) are imported.
- Foundation foods report energy as Atwater factors (nutrient 958/957) rather than
  208; the importer prefers 208, then 958, then 957.
- Raw/cooked state and cooking method are inferred from the description
  (e.g. "…, cooked, roasted").

### NIH Dietary Supplement Label Database (DSLD) — free, enabled by default
- https://dsld.od.nih.gov/ · API: https://dsld.od.nih.gov/api-guide
- Values are per label serving (e.g. "2 Softgel(s)"). Log supplements by serving
  or by individual unit (capsule/tablet).
- Unit conversions are only applied when unambiguous. Vitamin D IU → µg (×0.025)
  is converted. Vitamin A in IU and folate in plain µg are not: their µg RAE /
  µg DFE equivalents depend on the chemical form. These rows are kept as
  "other components" with a note, never silently guessed.
- Only rows whose name *is* the nutrient ("Vitamin C", "Vit. K", "Vitamin D3")
  are counted. A row named after a compound ("Magnesium Glycinate 2 g",
  "D-Alpha-Tocopheryl Acetate 143 mg") declares the compound's mass, not the
  nutrient's, so it is kept as an other component with a note.
- **%DV cross-check.** When a label row also gives a % Daily Value, the amount is
  checked against it, using both current and pre-2016 FDA Daily Values. If the
  amount is more than 5× off from what the %DV implies, it is **not counted** and
  is flagged on the food. This catches DSLD transcription errors seen in real
  records, e.g. "Iodine 109 mg (70% DV)" where the label means 109 mcg. Counted
  as-is, that would trigger a false upper-limit alert.
- **Chemical forms.** Vitamin A in IU, vitamin E in IU and folate in plain µg
  only convert once the form is known. If the label names the form ("as
  retinyl palmitate", "d-alpha tocopheryl", "folic acid"), the amount is
  converted at import using the NIH ODS factors and the factor is recorded.
  Otherwise the amount is kept, the day view shows that nutrient as **partly
  counted**, and the food page lets you choose the form from your label. That
  choice is recorded as your data and applied to past entries too.

  | Form | Factor (NIH ODS) |
  |---|---|
  | Vitamin A, retinol/retinyl esters | 1 IU = 0.3 µg RAE |
  | Vitamin A, supplemental β-carotene | 1 IU = 0.3 µg RAE |
  | Vitamin A, carotenoids from food | 1 IU = 0.05 µg RAE |
  | Vitamin E, natural (d-α, RRR) | 1 IU = 0.67 mg |
  | Vitamin E, synthetic (dl-α, all-rac) | 1 IU = 0.45 mg |
  | Folic acid | 1 µg = 1.7 µg DFE (FDA labeling) |
- Ingredients that aren't standard nutrients (botanicals, creatine, probiotics…)
  are kept as other components and totalled per day.

### Nutritionix — paid, enabled once its app ID and key are entered in Settings
- https://www.nutritionix.com/business/api
- Restaurant, branded and common foods. Per-serving values are converted to
  per 100 g using the serving weight.
- **Implemented from the published v2 API documentation; not yet run against a
  live account.** Check it with your own key before relying on it.

### Edamam Food Database — paid tiers, enabled once its app ID and key are entered in Settings
- https://developer.edamam.com/food-database-api
- **Implemented from the published v2 API documentation; not yet run against a
  live account.**

### Open Food Facts — free, crowdsourced, OFF by default
- https://world.openfoodfacts.org/ (ODbL)
- Only available when "Allow crowdsourced data" is switched on in Settings. Every
  record is stored and shown as `unverified`.

> **Licensing.** Commercial APIs often restrict caching or sharing records
> between users. This app stores imported records as shared foods. Read your
> contract and adjust if needed (e.g. make commercial imports private per user,
> or refresh them on a schedule).

## Other reputable options (not yet implemented)

Adding a source means one class in `backend/app/sources/` implementing `search`
and `fetch` and returning an `ExternalFood`, plus an entry in `registry.py`.

**Paid / licensed**
- **University of Minnesota NCC Food and Nutrient Database** (the database behind
  NDSR). Research-grade with very broad nutrient coverage. Licensed dataset, so it
  would need a file importer rather than an API adapter.
- **ESHA Research** (Food Processor / Genesis R&D). Large, curated, widely used
  for label compliance. Licensed dataset.
- **FatSecret Platform API** (premium tiers). Commercial API with branded and
  restaurant coverage.

**Free, government**
- **Canadian Nutrient File** (Health Canada)
- **UK Composition of Foods Integrated Dataset (CoFID)** — McCance & Widdowson
- **Australian Food Composition Database** (FSANZ)

Pricing and terms change. Check each vendor directly.

## Raw → cooked conversions

A **cooking yield** links a raw food to a cooking method:
`cooked weight = raw weight × yield factor`. It can optionally carry
**retention factors** (the fraction of each nutrient that survives cooking).
When you log a raw food by its cooked weight, the app converts back to raw mass,
applies retention factors, and records the calculation on the log entry.

Yields come from three places, in order of preference:

1. **Measured (best).** Weigh the food raw, cook it, weigh it again. This captures
   your actual pan, time and doneness. Trust: `user`.
2. **Published.** Enter values from a reference with a citation (required), e.g.:
   - USDA *Table of Cooking Yields for Meat and Poultry* (2014)
   - USDA *Table of Nutrient Retention Factors*, Release 6 (2007)

   Trust: `user`, because a person typed the values in. The citation stays on the record.
3. **Derived.** From a paired raw and cooked entry in FDC (e.g. "Chicken breast,
   raw" and "Chicken breast, roasted"). Protein barely leaves food during
   cooking, so `protein per 100 g raw ÷ protein per 100 g cooked` estimates the
   yield. The dry-matter ratio is shown as a cross-check; it reads low when fat
   renders out. Trust: the weaker of the two foods.

   After a USDA import the app does this automatically for every raw/cooked
   pair it can match, which gives about 1,000 shared yields. To keep the
   estimates sound, it only matches:
   - pairs within the lab datasets (Foundation, SR Legacy). Survey dishes
     include coatings and oil;
   - foods with at least 5 g protein per 100 g;
   - yields between 0.3 and 4, with none above 1 for meat, poultry or fish;
   - descriptions that differ only in preparation words (cooking method,
     salt, "drained", patty/crumbles/loaf). Dry grains and legumes count as
     the uncooked form.

   Examples: chicken breast 0.70 braised / 0.74 grilled; ground beef 85% lean
   0.67–0.76; pasta 2.24; white rice 2.65.

**When a yield has an analysed cooked entry** (all derived yields do), logging
by cooked weight uses that cooked entry's measured nutrients. It already
reflects cooking losses, so it's more accurate than applying retention factors
to the raw values.

**Retention factors** from the USDA table can be attached to any yield you
create: pick a profile such as "CHICKEN,ROASTED" or "VEG,GREEN,BOILED,DRAINED"
when adding the yield. The table's total-folate and vitamin A (IU) factors are
applied to folate (DFE) and vitamin A (RAE).

Without retention factors the app assumes nothing is lost, and says so on the
entry ("vitamins may be overstated"). This matters most for heat-sensitive
vitamins such as C, thiamin and folate. For whole dishes, the most accurate
approach is a **recipe**: weigh the ingredients raw, weigh the finished dish, and
log portions by cooked weight.

## Daily targets

- Micronutrients use the National Academies **Dietary Reference Intakes** for
  adults 19+ (RDA or AI, plus the Tolerable Upper Intake Level), following the
  NIH ODS DRI tables. Sodium and potassium use the 2019 update; the sodium max is
  the Chronic Disease Risk Reduction intake.
- Some ULs apply only to supplemental/fortificant forms: magnesium, folic acid,
  niacin, vitamin E, and preformed vitamin A. Those are compared against
  supplement intake only.
- Energy is a Mifflin-St Jeor estimate × activity factor. Macronutrient ranges are
  the AMDRs. Saturated fat and added sugars are capped at <10% of energy, per the
  Dietary Guidelines for Americans 2020–2025.
- Built-in values do not cover pregnancy, lactation or people under 19. The app
  shows only upper limits in those cases and asks for clinician-guided overrides.
- The values in `backend/app/services/targets.py` were transcribed by hand. Check
  them against the ODS tables before relying on them.
