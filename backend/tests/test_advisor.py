from datetime import UTC, datetime, timedelta

from anthropic.types.beta import BetaMessage

from app.config import get_settings
from app.main import app
from app.routers.advisor import get_anthropic_client


def message(content: list[dict], stop_reason: str) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    })


class FakeClient:
    """Stands in for anthropic.Anthropic; replays scripted responses and records requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        # Snapshot the history as sent (the caller keeps appending to the same list).
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def use(client):
    app.dependency_overrides[get_anthropic_client] = lambda: client


def test_tool_round_trip_and_persistence(user_client):
    user_client.put("/api/profile", json={"sex": "female", "birth_date": "1990-01-01", "timezone": "UTC"})
    user_client.post("/api/foods", json={"name": "Lentils, cooked", "nutrients": {"protein_g": 9}})
    user_client.post("/api/log", json={"food_id": 1, "quantity": 300, "consumed_at": datetime.now(UTC).isoformat()})
    today = datetime.now(UTC).date().isoformat()
    fake = FakeClient([
        message([{"type": "text", "text": "Let me check."},
                 {"type": "tool_use", "id": "toolu_1", "name": "get_day_summary", "input": {"date": today}}], "tool_use"),
        message([{"type": "text", "text": "You had 27 g of protein today."}], "end_turn"),
    ])
    use(fake)
    resp = user_client.post("/api/advisor/chat", json={"message": "How much protein today?"})
    assert resp.status_code == 200, resp.text
    convo = resp.json()
    assert convo["title"] == "How much protein today?"
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    assert convo["messages"][1]["tools_used"] == ["get_day_summary"]
    assert convo["messages"][1]["text"].endswith("27 g of protein today.")

    first, second = fake.requests
    assert first["model"] == get_settings().advisor_model
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert all(t["strict"] for t in first["tools"] if "input_schema" in t)
    web = {t["name"]: t for t in first["tools"] if "input_schema" not in t}
    assert set(web) == {"web_search", "web_fetch"} and "ods.od.nih.gov" in web["web_search"]["allowed_domains"]
    assert "<context>Today is" in first["messages"][0]["content"][0]["text"]
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert '"Protein": "27 g"' in tool_result["content"]

    # A follow-up replays the full stored history, unchanged and append-only.
    fake2 = FakeClient([message([{"type": "text", "text": "Sure."}], "end_turn")])
    use(fake2)
    user_client.post("/api/advisor/chat", json={"message": "Thanks", "conversation_id": convo["id"]})
    replay = fake2.requests[0]["messages"]
    assert len(replay) == 5
    assert replay[:4] == second["messages"] + [{"role": "assistant", "content": [
        {"type": "text", "text": "You had 27 g of protein today."}]}]


def test_tool_errors_are_reported_to_the_model(user_client):
    fake = FakeClient([
        message([{"type": "tool_use", "id": "toolu_1", "name": "get_food_details", "input": {"food_id": 999}}], "tool_use"),
        message([{"type": "text", "text": "That food doesn't exist."}], "end_turn"),
    ])
    use(fake)
    assert user_client.post("/api/advisor/chat", json={"message": "food 999?"}).status_code == 200
    result = fake.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


def test_refusal_is_replaced_and_partial_output_discarded(user_client):
    use(FakeClient([message([{"type": "text", "text": "partial"}], "refusal")]))
    convo = user_client.post("/api/advisor/chat", json={"message": "hi"}).json()
    assert convo["messages"][-1]["text"] == "I can't help with that request."


def test_tool_rounds_are_capped(user_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "advisor_max_tool_rounds", 1)
    loop = {"type": "tool_use", "id": "toolu_x", "name": "list_recipes", "input": {}}
    fake = FakeClient([message([loop], "tool_use"), message([{"type": "text", "text": "Done."}], "end_turn")])
    use(fake)
    assert user_client.post("/api/advisor/chat", json={"message": "go"}).status_code == 200
    assert fake.requests[-1]["tool_choice"] == {"type": "none"}


def test_daily_limit_and_privacy(user_client, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "advisor_daily_message_limit", 1)
    use(FakeClient([message([{"type": "text", "text": "ok"}], "end_turn")]))
    convo = user_client.post("/api/advisor/chat", json={"message": "one"}).json()
    assert user_client.post("/api/advisor/chat", json={"message": "two"}).status_code == 429
    client.cookies.clear()
    client.post("/api/auth/register", json={"email": "b@example.com", "password": "another long password"})
    assert client.get(f"/api/advisor/conversations/{convo['id']}").status_code == 404
    assert client.get("/api/advisor/conversations").json() == []


def test_web_research_can_be_turned_off(user_client):
    user_client.put("/api/admin/settings", json={"values": {"advisor_web_research": False}})
    fake = FakeClient([message([{"type": "text", "text": "ok"}], "end_turn")])
    use(fake)
    user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert all("input_schema" in t for t in fake.requests[0]["tools"])


def test_cited_sources_are_shown(user_client):
    use(FakeClient([message([
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "magnesium UL"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": []},
        {"type": "text", "text": "The UL is 350 mg from supplements.", "citations": [
            {"type": "web_search_result_location", "url": "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
             "title": "Magnesium - Health Professional Fact Sheet", "cited_text": "350 mg", "encrypted_index": "x"}]},
    ], "end_turn")]))
    convo = user_client.post("/api/advisor/chat", json={"message": "Mg UL?"}).json()
    reply = convo["messages"][-1]
    assert reply["tools_used"] == ["web_search"]
    assert reply["sources"] == [{"url": "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
                                 "title": "Magnesium - Health Professional Fact Sheet"}]


def test_plan_proposal_review(user_client):
    food = user_client.post("/api/foods", json={"name": "Greek yogurt", "nutrients": {"protein_g": 10}}).json()
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    use(FakeClient([
        message([{"type": "tool_use", "id": "toolu_1", "name": "propose_plan_items", "input": {
            "rationale": "More protein at breakfast.",
            "items": [
                {"date": tomorrow, "meal": "breakfast", "food_id": food["id"], "recipe_id": None, "quantity": 200, "unit": "g"},
                {"date": tomorrow, "meal": "breakfast", "food_id": 99999, "recipe_id": None, "quantity": 1, "unit": "g"},
            ]}}],
                "tool_use"),
        message([{"type": "text", "text": "I proposed yogurt for breakfast."}], "end_turn"),
    ]))
    convo = user_client.post("/api/advisor/chat", json={"message": "plan breakfast"}).json()
    [proposal] = convo["proposals"]
    assert proposal["status"] == "pending" and [i["label"] for i in proposal["items"]] == ["Greek yogurt"]
    params = {"start": tomorrow, "end": tomorrow}
    assert user_client.get("/api/plan", params=params).json()[0]["items"] == []  # nothing added yet
    assert user_client.post(f"/api/advisor/proposals/{proposal['id']}/accept", json={"indexes": [5]}).status_code == 422
    accepted = user_client.post(f"/api/advisor/proposals/{proposal['id']}/accept", json={}).json()
    assert accepted["status"] == "accepted" and accepted["accepted_indexes"] == [0]
    [item] = user_client.get("/api/plan", params=params).json()[0]["items"]
    assert item["origin"] == "advisor" and item["quantity"] == 200
    assert user_client.post(f"/api/advisor/proposals/{proposal['id']}/dismiss").status_code == 409


def real_client(handler):
    """The actual SDK, with HTTP answered by `handler`, so the request is checked as it goes over the wire."""
    import anthropic
    import httpx2

    return anthropic.Anthropic(api_key="sk-ant-test", max_retries=0,
                               http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))


def test_request_as_sent_by_the_sdk(user_client):
    import json as _json

    import httpx2

    sent = []

    def handler(request):
        sent.append((request.headers, _json.loads(request.content)))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "Hello."}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "input_transformations": [{"type": "thinking_dropped", "path": "messages.1.content.0",
                                       "reason": "prefix_binding_mismatch"}]})

    use(real_client(handler))
    resp = user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert resp.status_code == 200, resp.text
    headers, body = sent[0]
    assert set(headers["anthropic-beta"].split(",")) == {"server-side-fallback-2026-07-01",
                                                          "thinking-binding-controls-2026-08-01"}
    assert body["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert body["fallbacks"] == "default" and body["output_config"] == {"effort": get_settings().advisor_effort}
    assert "temperature" not in body and body["tool_choice"] == {"type": "auto"}
    assert all(t.get("strict") for t in body["tools"] if "input_schema" in t)


def test_api_errors_explain_themselves(user_client):
    import httpx2

    def rejected(request):
        return httpx2.Response(400, headers={"request-id": "req_abc"}, json={
            "type": "error", "error": {"type": "invalid_request_error", "message": "tools.3: something is wrong"}})

    use(real_client(rejected))
    resp = user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "The AI service rejected the request (400): tools.3: something is wrong [request req_abc]"

    use(real_client(lambda request: httpx2.Response(529, json={
        "type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})))
    resp = user_client.post("/api/advisor/chat", json={"message": "hi"})
    assert resp.status_code == 503 and "try again" in resp.json()["detail"]
    assert user_client.get("/api/advisor/conversations").json() == []  # failed turns aren't saved


def test_reply_cut_off_mid_tool_call_doesnt_break_the_conversation(user_client):
    cut = [{"type": "text", "text": "Let me check"}, {"type": "tool_use", "id": "toolu_cut", "name": "list_recipes", "input": {}}]
    fake = FakeClient([message(cut, "max_tokens"), message([{"type": "text", "text": "Fine."}], "end_turn")])
    use(fake)
    convo = user_client.post("/api/advisor/chat", json={"message": "first"}).json()
    assert user_client.post("/api/advisor/chat", json={"conversation_id": convo["id"], "message": "again"}).status_code == 200
    sent = fake.requests[-1]["messages"]
    assert not any(b.get("type") == "tool_use" for m in sent if m["role"] == "assistant" for b in m["content"])


def test_conversations_saved_with_an_unanswered_tool_call_are_repaired():
    from app.advisor.agent import _repaired

    history = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "cut"}, {"type": "tool_use", "id": "b", "name": "x",
                                                                            "input": {}}]},
    ]
    fixed = _repaired(history)
    assert fixed[1] == history[1]  # answered calls stay
    assert fixed[3]["content"] == [{"type": "text", "text": "cut"}]


def test_food_search_tolerates_a_serving_without_a_size(user_client, db_session):
    from app.advisor.tools import run_tool
    from app.models import User

    user_client.post("/api/foods", json={"name": "Magnesium glycinate", "kind": "supplement", "basis": "serving",
                                         "serving_unit": "capsule", "nutrients": {"magnesium_mg": 100}})
    user = db_session.query(User).one()
    out = run_tool(db_session, user, "search_foods", {"query": "magnesium"}, None, get_settings())
    assert "per serving (capsule)" in out


def test_targets_tool_counts_todays_exercise(user_client, db_session):
    import json

    from app.advisor.tools import run_tool
    from app.models import User

    user_client.put("/api/profile", json={"sex": "male", "birth_date": "1985-01-01", "height_cm": 180,
                                          "weight_kg": 80, "timezone": "UTC"})
    user = db_session.query(User).one()
    before = json.loads(run_tool(db_session, user, "get_profile_and_targets", {}, None, get_settings()))
    today = datetime.now(UTC).date().isoformat()
    user_client.post("/api/exercise", json={"date": today, "name": "Ride", "duration_min": 60, "reported_kcal": 580})
    after = json.loads(run_tool(db_session, user, "get_profile_and_targets", {}, None, get_settings()))
    assert after["net_exercise_kcal_today"] == 500  # 580 reported, less 80 kcal resting
    assert after["targets"]["energy_kcal"]["target"] == before["targets"]["energy_kcal"]["target"] + 500
