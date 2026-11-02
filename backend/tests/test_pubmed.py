import json

import httpx
import respx

from app.advisor import pubmed
from app.config import get_settings
from tests.conftest import FIXTURES, load_fixture
from tests.test_advisor import FakeClient, message, use

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def test_parse_articles():
    by_id = {a["pmid"]: a for a in pubmed.parse_articles((FIXTURES / "pubmed_efetch.xml").read_bytes())}
    assert set(by_id) == {"39070254", "35984306", "9500320"}
    review = by_id["39070254"]
    assert review["title"].startswith("The effects of creatine supplementation on cognitive function")
    assert review["journal"] == "Frontiers in nutrition" and review["year"] == "2024"
    assert "Systematic Review" in review["publication_types"]
    assert review["doi"] == "10.3389/fnut.2024.1424972" and review["url"] == "https://pubmed.ncbi.nlm.nih.gov/39070254/"
    assert review["abstract"].startswith("BACKGROUND: ") and not review["retracted"]
    assert len(review["abstract"]) <= pubmed.MAX_ABSTRACT_CHARS + 2
    assert by_id["9500320"]["retracted"]


@respx.mock
def test_search_applies_filter_and_key_and_keeps_order():
    settings = get_settings().model_copy(update={"ncbi_api_key": "k123"})
    search = respx.get(ESEARCH).respond(json=load_fixture("pubmed_esearch.json"))
    fetch = respx.get(EFETCH).respond(content=(FIXTURES / "pubmed_efetch.xml").read_bytes())
    with httpx.Client() as client:
        result = pubmed.search(client, settings, "creatine supplementation older adults", "reviews_and_meta_analyses", 2)
    params = search.calls.last.request.url.params
    assert params["term"].endswith("AND (systematic[sb] OR meta-analysis[pt])")
    assert params["api_key"] == "k123" and params["tool"] == "mealplan" and params["retmax"] == "2"
    assert fetch.calls.last.request.url.params["id"] == "39070254,35984306"
    assert [a["pmid"] for a in result["articles"]] == ["39070254", "35984306"]
    assert result["total_matches"] == 46


@respx.mock
def test_advisor_cites_pubmed_articles(user_client):
    respx.get(ESEARCH).respond(json=load_fixture("pubmed_esearch.json"))
    respx.get(EFETCH).respond(content=(FIXTURES / "pubmed_efetch.xml").read_bytes())
    fake = FakeClient([
        message([{"type": "tool_use", "id": "toolu_1", "name": "search_pubmed", "input": {
            "query": "creatine cognition", "evidence": "reviews_and_meta_analyses", "max_results": 2}}], "tool_use"),
        message([{"type": "text", "text": "A 2024 meta-analysis (PMID 39070254) found a small memory benefit."}],
                "end_turn"),
    ])
    use(fake)
    convo = user_client.post("/api/advisor/chat", json={"message": "Does creatine help memory?"}).json()
    assert "search_pubmed" in {t["name"] for t in fake.requests[0]["tools"]}
    result = json.loads(fake.requests[1]["messages"][-1]["content"][0]["content"])
    assert result["articles"][0]["pmid"] == "39070254"
    reply = convo["messages"][-1]
    assert reply["tools_used"] == ["search_pubmed"]
    assert reply["sources"] == [{"url": "https://pubmed.ncbi.nlm.nih.gov/39070254/",
                                 "title": result["articles"][0]["title"]}]


@respx.mock
def test_pubmed_errors_and_switch(user_client):
    respx.get(ESEARCH).respond(status_code=503)
    fake = FakeClient([
        message([{"type": "tool_use", "id": "toolu_1", "name": "search_pubmed", "input": {
            "query": "x", "evidence": "any", "max_results": 3}}], "tool_use"),
        message([{"type": "text", "text": "PubMed is unavailable."}], "end_turn"),
    ])
    use(fake)
    assert user_client.post("/api/advisor/chat", json={"message": "x"}).status_code == 200
    assert "PubMed search failed" in fake.requests[1]["messages"][-1]["content"][0]["content"]

    user_client.put("/api/admin/settings", json={"values": {"advisor_pubmed": False}})
    fake = FakeClient([message([{"type": "text", "text": "ok"}], "end_turn")])
    use(fake)
    user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert "search_pubmed" not in {t.get("name") for t in fake.requests[0]["tools"]}


@respx.mock
def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(pubmed, "RETRY_DELAY_SECONDS", 0)
    respx.get(ESEARCH).mock(side_effect=[httpx.Response(429), httpx.Response(200, json=load_fixture("pubmed_esearch.json"))])
    respx.get(EFETCH).respond(content=(FIXTURES / "pubmed_efetch.xml").read_bytes())
    with httpx.Client() as client:
        result = pubmed.search(client, get_settings(), "creatine", "any", 2)
    assert len(result["articles"]) == 2
