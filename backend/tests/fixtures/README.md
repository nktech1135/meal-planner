Recorded responses used by the source-adapter tests.

- `fdc_*.json` — USDA FoodData Central API (public domain, CC0), recorded 2026-10-30.
- `dsld_*.json` — NIH ODS Dietary Supplement Label Database API (U.S. government data), recorded 2026-10-30.
- `pubmed_*` — NCBI E-utilities esearch/efetch (PubMed records are U.S. government data; abstracts
  remain the publishers'), recorded 2026-11-02. The efetch file adds PMID 9500320, a retracted paper.

Nutritionix, Edamam and Open Food Facts tests use small synthetic payloads shaped
like those services' documented responses (see `tests/test_sources.py`).
