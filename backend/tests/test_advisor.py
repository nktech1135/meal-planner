from datetime import UTC, datetime

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
    assert all(t["strict"] for t in first["tools"])
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
