"""PubMed look-ups for the advisor, through NCBI's E-utilities API.

Returns structured records (publication types, year, journal, retraction status,
abstract) so the advisor can weigh the strength of evidence instead of reading web pages.
https://www.ncbi.nlm.nih.gov/books/NBK25499/
"""

import time
import xml.etree.ElementTree as ET

import httpx

from app.config import Settings

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_ABSTRACT_CHARS = 2500
RETRY_DELAY_SECONDS = 0.5

# Appended to the query to narrow results to stronger study designs.
EVIDENCE_FILTERS = {
    "any": "",
    "reviews_and_meta_analyses": " AND (systematic[sb] OR meta-analysis[pt])",
    "randomized_trials": " AND randomized controlled trial[pt]",
    "guidelines": " AND (guideline[pt] OR practice guideline[pt])",
}


class PubMedError(RuntimeError):
    pass


def _params(settings: Settings, **extra) -> dict:
    params = {"db": "pubmed", "tool": "mealplan", **extra}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


def _text(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _year(article: ET.Element) -> str | None:
    date = article.find("Journal/JournalIssue/PubDate")
    if date is None:
        return None
    year = date.findtext("Year") or (date.findtext("MedlineDate") or "")[:4]
    return year or None


def parse_articles(xml: bytes | str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for node in root.iter("PubmedArticle"):
        citation = node.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        if article is None:
            continue
        pmid = citation.findtext("PMID")
        parts = []
        for part in article.findall("Abstract/AbstractText"):
            label, text = part.get("Label"), _text(part)
            parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(parts)
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + " …"
        types = [_text(t) for t in article.findall("PublicationTypeList/PublicationType")]
        retracted = "Retracted Publication" in types or any(
            c.get("RefType") == "RetractionIn" for c in citation.iter("CommentsCorrections"))
        doi = next((_text(e) for e in article.findall("ELocationID") if e.get("EIdType") == "doi"), None)
        out.append({
            "pmid": pmid, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "title": _text(article.find("ArticleTitle")),
            "journal": article.findtext("Journal/Title"), "year": _year(article), "publication_types": types,
            "retracted": retracted, "doi": doi, "abstract": abstract or None,
        })
    return out


def _get(client: httpx.Client, settings: Settings, url: str, params: dict, attempts: int = 3) -> httpx.Response:
    """GET with a short wait and retry when NCBI's rate limit (3 requests a second without a key) answers 429."""
    for attempt in range(attempts):
        resp = client.get(url, params=params, timeout=settings.http_timeout_seconds)
        if resp.status_code != 429 or attempt == attempts - 1:
            break
        time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    resp.raise_for_status()
    return resp


def search(client: httpx.Client, settings: Settings, query: str, evidence: str = "any", max_results: int = 5) -> dict:
    term = query.strip() + EVIDENCE_FILTERS.get(evidence, "")
    retmax = max(1, min(10, max_results))
    try:
        resp = _get(client, settings, f"{EUTILS}/esearch.fcgi",
                    _params(settings, term=term, retmode="json", retmax=retmax, sort="relevance"))
        found = resp.json()["esearchresult"]
        ids = found.get("idlist") or []
        articles = []
        if ids:
            resp = _get(client, settings, f"{EUTILS}/efetch.fcgi", _params(settings, id=",".join(ids), retmode="xml"))
            by_id = {a["pmid"]: a for a in parse_articles(resp.content)}
            articles = [by_id[i] for i in ids if i in by_id]  # keep relevance order
    except (httpx.HTTPError, KeyError, ValueError, ET.ParseError) as exc:
        raise PubMedError(f"PubMed search failed: {exc}") from None
    return {"query": term, "total_matches": int(found.get("count") or 0), "articles": articles}
