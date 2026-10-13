"""Integration tests of the service — with a REAL Postgres and a REAL bank MCP server.

Only the LLM is replaced by a tiny deterministic fake (conftest.py), so the tests
check the plumbing without spending tokens: MCP tool calls hitting the real bank
data, agent memory in Postgres, sessions, and continuing ONE session from the
web and from Telegram.

    uv run pytest -q
"""


def new_session(client, source="web") -> int:
    return client.post("/api/sessions", json={"source": source}).json()["id"]


def say(client, session_id: int, text: str, source="web") -> dict:
    return client.post(f"/api/sessions/{session_id}/chat", json={"text": text, "source": source}).json()


def test_agent_calls_mcp_against_real_data(client):
    reply = say(client, new_session(client), "сколько кредитов в банке?")
    assert reply["tools"] == [{"name": "run_sql", "args": {"query": "SELECT count(*) AS loans FROM loans"}}]
    assert reply["answer"] == "В базе **682** кредитов."              # real number from Postgres via MCP


def test_sessions_list_and_history(client):
    session_id = new_session(client)
    say(client, session_id, "сколько кредитов?")
    listed = client.get("/api/sessions").json()
    assert listed[0]["id"] == session_id and listed[0]["title"] == "сколько кредитов?"
    history = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["tools"][0]["name"] == "run_sql"


def test_one_session_from_web_and_telegram(client):
    session_id = new_session(client, "web")
    say(client, session_id, "привет из веба", "web")
    reply = say(client, session_id, "а это из телеги", "telegram")    # what the bot sends after /continue
    assert "сообщений от вас в этой сессии: 2" in reply["answer"]       # it remembers the web message
    history = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [m["content"] for m in history if m["role"] == "user"] == ["привет из веба", "а это из телеги"]


def test_session_started_in_telegram_is_listed_for_the_web(client):
    session_id = new_session(client, "telegram")
    say(client, session_id, "старт в телеге", "telegram")
    listed = {s["id"]: s for s in client.get("/api/sessions").json()}
    assert listed[session_id]["source"] == "telegram" and listed[session_id]["title"] == "старт в телеге"


def test_empty_model_answer_is_retried(client):
    session_id = new_session(client)
    assert say(client, session_id, "пусто")["answer"] == "Ответ со второй попытки."
    history = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [m["content"] for m in history] == ["пусто", "Ответ со второй попытки."]   # the nudge isn't stored


def test_errors(client):
    session_id = new_session(client)
    response = client.post(f"/api/sessions/{session_id}/chat", json={"text": "boom"})
    assert response.status_code == 502 and "provider is down" in response.json()["detail"]
    assert client.get("/api/sessions/999999").status_code == 404
    assert client.post("/api/sessions/999999/chat", json={"text": "hi"}).status_code == 404


def test_web_page_is_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "Bank analyst" in page.text
