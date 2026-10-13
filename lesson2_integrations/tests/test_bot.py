"""End-to-end tests of the Telegram bot — without Telegram.

Telegram updates are fed straight into the aiogram dispatcher, and what the bot
sends is recorded instead. Everything behind the bot is real: our API on a port,
Postgres, the bank MCP server (only the LLM is the fake from conftest.py).
"""

import asyncio
import re
from datetime import datetime

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from app import config
from app.bot import create_dispatcher

USER = User(id=4242, is_bot=False, first_name="Student")


class RecordingSession(BaseSession):
    """Pretends to be Telegram: remembers every message the bot sends."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def make_request(self, bot, method, timeout=None):
        assert isinstance(method, SendMessage), f"unexpected Telegram call {type(method).__name__}"
        self.sent.append(method.text)
        return Message(message_id=len(self.sent), date=datetime.now(),
                       chat=Chat(id=method.chat_id, type="private"), text=method.text)

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def close(self) -> None:
        pass


class TelegramChat:
    """A user typing into the bot; `say` returns the bot's replies."""

    def __init__(self, api_url: str) -> None:
        self.session = RecordingSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.dp = create_dispatcher(api_url)
        self.updates = 0

    async def say(self, text: str) -> list[str]:
        self.updates += 1
        before = len(self.session.sent)
        message = Message(message_id=self.updates, date=datetime.now(), text=text, from_user=USER,
                          chat=Chat(id=USER.id, type="private"))
        await self.dp.feed_update(self.bot, Update(update_id=self.updates, message=message))
        return self.session.sent[before:]


def session_number(reply: str) -> int:
    return int(re.search(r"— сессия #(\d+)$", reply).group(1))


@pytest.fixture(autouse=True)
def everyone_allowed(monkeypatch):
    """Ignore TELEGRAM_ALLOWED_USERS from the local .env."""
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USERS", set())


@pytest.fixture
def run():
    loop = asyncio.new_event_loop()
    yield loop.run_until_complete
    loop.close()


def test_every_answer_ends_with_the_session_number(api_url, run):
    tg = TelegramChat(api_url)
    [first] = run(tg.say("привет"))
    [second] = run(tg.say("сколько кредитов в банке?"))
    assert session_number(first) == session_number(second)            # same session
    assert "**682**" in second                                         # real data via MCP
    session = httpx.get(f"{api_url}/api/sessions/{session_number(first)}").json()
    assert session["source"] == "telegram" and session["title"] == "привет"


def test_new_starts_a_fresh_session(api_url, run):
    tg = TelegramChat(api_url)
    [before] = run(tg.say("до /new"))
    [started] = run(tg.say("/new"))
    [after] = run(tg.say("эхо"))
    assert session_number(after) != session_number(before) and f"#{session_number(after)}" in started
    assert "сообщений от вас в этой сессии: 1" in after                # no memory of the old session


def test_continue_a_web_session_in_telegram_and_back(api_url, run):
    web = httpx.post(f"{api_url}/api/sessions", json={"source": "web"}).json()["id"]
    httpx.post(f"{api_url}/api/sessions/{web}/chat", json={"text": "вопрос из веба"}, timeout=30)

    tg = TelegramChat(api_url)
    [reply] = run(tg.say(f"/continue {web}"))
    assert f"#{web}" in reply
    [reply] = run(tg.say("а теперь из телеги"))
    assert "сообщений от вас в этой сессии: 2" in reply and session_number(reply) == web

    history = httpx.get(f"{api_url}/api/sessions/{web}/messages").json()   # what the web page shows
    assert [m["content"] for m in history if m["role"] == "user"] == ["вопрос из веба", "а теперь из телеги"]


def test_bad_input_and_agent_errors(api_url, run):
    tg = TelegramChat(api_url)
    assert "Укажите номер" in run(tg.say("/continue abc"))[0]
    assert "нет" in run(tg.say("/continue 999999"))[0]
    [reply] = run(tg.say("boom"))
    assert reply.startswith("⚠️ agent error") and re.search(r"— сессия #\d+$", reply)


def test_allow_list_keeps_strangers_out(api_url, run, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USERS", {1})        # only user 1, we are 4242
    tg = TelegramChat(api_url)
    assert run(tg.say("сколько кредитов?")) == ["Нет доступа."]
    assert run(tg.say("/new")) == []
