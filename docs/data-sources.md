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

## Implemented sources

### USDA FoodData Central — free, enabled by default
- https://fdc.nal.usda.gov/ · API guide: https://fdc.nal.usda.gov/api-guide
- Public domain (CC0). Get a free API key at https://fdc.nal.usda.gov/api-key-signup
  and set `USDA_FDC_API_KEY`. The default `DEMO_KEY` is heavily rate-limited.
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
- Ingredients that aren't standard nutrients (botanicals, creatine, probiotics…)
  are kept as other components and totalled per day.

### Nutritionix — paid, enabled when `NUTRITIONIX_APP_ID`/`NUTRITIONIX_APP_KEY` are set
- https://www.nutritionix.com/business/api
- Restaurant, branded and common foods. Per-serving values are converted to
  per 100 g using the serving weight.
- **Implemented from the published v2 API documentation; not yet run against a
  live account.** Check it with your own key before relying on it.

### Edamam Food Database — paid tiers, enabled when `EDAMAM_APP_ID`/`EDAMAM_APP_KEY` are set
- https://developer.edamam.com/food-database-api
- **Implemented from the published v2 API documentation; not yet run against a
  live account.**

### Open Food Facts — free, crowdsourced, OFF by default
- https://world.openfoodfacts.org/ (ODbL)
- Only available with `ENABLE_UNVERIFIED_SOURCES=true`. Every record is stored and
  shown as `unverified`.

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

No yield values are pre-loaded. Typing numbers in from memory would defeat the
point of tracking provenance. Bulk import of the USDA yield and retention tables
(CSV) is a natural next step.

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
