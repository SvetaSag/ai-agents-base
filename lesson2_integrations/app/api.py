"""HTTP API + web chat. One backend for both front-ends.

    browser  ─┐
              ├─▶  this API  ─▶ LangGraph agent ─▶ bank MCP server ─▶ Postgres «bank»
    Telegram ─┘        │
                       └─▶ Postgres «agent»: agent memory (checkpointer) + sessions table

The web page and the Telegram bot call the same endpoints, so a session started
in one is continued in the other just by its number.

    GET  /                               the web chat (static/index.html)
    GET  /api/sessions                   all sessions, newest first
    POST /api/sessions                   new session            {"source": "web" | "telegram"}
    GET  /api/sessions/{id}              one session
    GET  /api/sessions/{id}/messages     its conversation (read from the agent's memory)
    POST /api/sessions/{id}/chat         send a message, get the answer   {"text": "...", "source": "..."}

Run locally:  uvicorn app.api:app --port 8080   (docker compose does this for you)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from app import agent, config

log = logging.getLogger("api")
PAGE = Path(__file__).parent / "static" / "index.html"

# the session list; the messages themselves live in the agent's memory under thread_id = id
SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id         serial PRIMARY KEY,
    title      text,                                -- the first message
    source     text NOT NULL,                       -- where it was started: web | telegram
    updated_at timestamptz NOT NULL DEFAULT now()
)"""


class NewSession(BaseModel):
    source: str = "web"


class Message(BaseModel):
    text: str
    source: str = "web"


async def connect_mcp() -> tuple[list, str]:
    """In docker the MCP server may still be starting — retry for up to a minute."""
    for attempt in range(30):
        try:
            return await agent.load_bank_tools(config.BANK_MCP_URL)
        except Exception as error:
            log.warning("MCP server not ready yet (%s)", error)
            await asyncio.sleep(2)
    raise RuntimeError(f"cannot reach the bank MCP server at {config.BANK_MCP_URL}")


def create_app(llm=None) -> FastAPI:
    """`llm` can be replaced in tests; by default — the model from .env via OpenRouter."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # runs once at startup: connect to the MCP server and Postgres, build the agent
        model = llm or ChatOpenAI(model=config.MODEL, base_url="https://openrouter.ai/api/v1",
                                  api_key=config.OPENROUTER_API_KEY)
        tools, schema = await connect_mcp()
        async with AsyncConnectionPool(config.AGENT_DSN, open=False,
                                       kwargs={"autocommit": True, "row_factory": dict_row}) as pool:
            async with pool.connection() as conn:
                await conn.execute(SESSIONS_TABLE)
            checkpointer = AsyncPostgresSaver(pool)        # agent memory in the same database
            await checkpointer.setup()                     # creates LangGraph's tables once
            app.state.pool = pool
            app.state.graph = agent.build_graph(model, tools, schema, checkpointer)
            log.info("ready: %d MCP tools, model %s", len(tools), config.MODEL)
            yield

    app = FastAPI(title="Bank analyst", lifespan=lifespan)

    async def sql(query: str, params: tuple = ()) -> list[dict]:
        async with app.state.pool.connection() as conn:
            cursor = await conn.execute(query, params)
            return await cursor.fetchall() if cursor.description else []

    async def get_session(session_id: int) -> dict:
        rows = await sql("SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not rows:
            raise HTTPException(404, f"session {session_id} not found")
        return rows[0]

    @app.get("/")
    async def page():
        return FileResponse(PAGE)

    @app.get("/api/sessions")
    async def list_sessions():
        return await sql("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 50")

    @app.post("/api/sessions")
    async def new_session(body: NewSession):
        return (await sql("INSERT INTO sessions (source) VALUES (%s) RETURNING *", (body.source,)))[0]

    @app.get("/api/sessions/{session_id}")
    async def one_session(session_id: int):
        return await get_session(session_id)

    @app.get("/api/sessions/{session_id}/messages")
    async def messages(session_id: int):
        await get_session(session_id)
        return await agent.history(app.state.graph, session_id)

    @app.post("/api/sessions/{session_id}/chat")
    async def chat(session_id: int, body: Message):
        await get_session(session_id)
        await sql("UPDATE sessions SET updated_at = now(), title = COALESCE(title, left(%s, 60)) WHERE id = %s",
                  (body.text, session_id))
        try:
            reply = await agent.chat(app.state.graph, session_id, body.text)
        except Exception as error:                         # e.g. the LLM provider is down
            log.exception("agent failed")
            raise HTTPException(502, f"agent error: {str(error)[:300]}")
        return {"session_id": session_id, **reply}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
for noisy in ("httpx", "mcp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
app = create_app()
