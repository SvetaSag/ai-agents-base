"""Telegram bot — one more front-end for the same API and the same sessions.

The bot doesn't touch the database or the agent: it calls our HTTP API, exactly
like the web page. That's why sessions are shared — start in the browser,
continue here with /continue <number>, and back.

    /new          start a new session
    /continue 12  continue session #12 (started here or in the web chat)
    any text      → the agent; every answer ends with the session number

Run:  python -m app.bot    (needs TELEGRAM_BOT_TOKEN; in docker: --profile telegram)
"""

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app import config

HELP = ("Я аналитик банка: отвечаю на вопросы по данным чешского банка (1993–1998).\n\n"
        "/new — новая сессия\n"
        "/continue 12 — продолжить сессию №12 (из Telegram или из веб-чата)\n\n"
        "Просто напишите вопрос, например: «сколько у банка клиентов?»")


def create_dispatcher(api_url: str) -> Dispatcher:
    dp = Dispatcher()
    api = httpx.AsyncClient(base_url=api_url, timeout=300)   # the agent can think for a while
    current: dict[int, int] = {}                             # Telegram chat id → session number

    async def new_session(chat_id: int) -> int:
        session = (await api.post("/api/sessions", json={"source": "telegram"})).json()
        current[chat_id] = session["id"]
        return session["id"]

    def allowed(message: Message) -> bool:                   # optional allow-list from .env
        return not config.TELEGRAM_ALLOWED_USERS or message.from_user.id in config.TELEGRAM_ALLOWED_USERS

    @dp.message(Command("start", "help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP)

    @dp.message(Command("new"))
    async def on_new(message: Message) -> None:
        if allowed(message):
            session_id = await new_session(message.chat.id)
            await message.answer(f"Новая сессия #{session_id}. Пишите вопрос.")

    @dp.message(Command("continue"))
    async def on_continue(message: Message, command: CommandObject) -> None:
        if not allowed(message):
            return
        if not (command.args or "").strip().isdigit():
            await message.answer("Укажите номер сессии: /continue 12")
            return
        session_id = int(command.args)
        if (await api.get(f"/api/sessions/{session_id}")).status_code == 404:
            await message.answer(f"Сессии #{session_id} нет.")
            return
        current[message.chat.id] = session_id
        await message.answer(f"Продолжаем сессию #{session_id}. Агент помнит весь разговор — пишите.")

    @dp.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        if not allowed(message):
            await message.answer("Нет доступа.")
            return
        session_id = current.get(message.chat.id) or await new_session(message.chat.id)
        response = await api.post(f"/api/sessions/{session_id}/chat",
                                  json={"text": message.text, "source": "telegram"})
        answer = response.json()["answer"] if response.status_code == 200 else f"⚠️ {response.json()['detail']}"
        text = f"{answer}\n\n— сессия #{session_id}"
        for start in range(0, len(text), 4000):              # Telegram limit: 4096 chars per message
            await message.answer(text[start:start + 4000])

    return dp


async def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (get one from @BotFather and put it into .env)")
    await create_dispatcher(config.API_URL).start_polling(Bot(config.TELEGRAM_BOT_TOKEN))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
