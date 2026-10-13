"""Shared fixtures: a test database, a real bank MCP server, and the API with a fake LLM.

Needs `docker compose up -d postgres` with the dataset loaded. Uses a separate
database `agent_test`, so real chat sessions stay untouched.
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time

import psycopg
import pytest

ADMIN = "postgresql://postgres:postgres@localhost:5434/postgres"
MCP_PORT = 8099   # note: 8021 is taken by a macOS launchd service on some machines
API_PORT = 8098

# configure the app BEFORE importing it
os.environ["AGENT_DSN"] = "postgresql://postgres:postgres@localhost:5434/agent_test"
os.environ["BANK_MCP_URL"] = f"http://localhost:{MCP_PORT}/mcp"

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

from app.agent import NUDGE  # noqa: E402


class FakeAnalyst(BaseChatModel):
    """Scripted model: asks for SQL on 'кредит', answers from the tool result, returns an
    empty answer on 'пусто' (and a real one when nudged), fails on 'boom', echoes otherwise."""

    @property
    def _llm_type(self) -> str:
        return "fake-analyst"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        last = messages[-1]
        if last.content == NUDGE:                       # the agent's retry after an empty answer
            message = AIMessage("Ответ со второй попытки.")
        elif "пусто" in last.content:                   # a model that returns an empty answer
            message = AIMessage("")
        elif last.type == "tool":
            count = re.search(r"\| (\d+) \|", str(last.content)).group(1)
            message = AIMessage(f"В базе **{count}** кредитов.")
        elif "boom" in last.content:
            raise RuntimeError("provider is down")
        elif "кредит" in last.content:
            message = AIMessage("", tool_calls=[{"name": "run_sql", "id": "call_1",
                                                 "args": {"query": "SELECT count(*) AS loans FROM loans"}}])
        else:
            human = [m.content for m in messages if m.type == "human"]
            message = AIMessage(f"Эхо: {last.content} (сообщений от вас в этой сессии: {len(human)})")
        return ChatResult(generations=[ChatGeneration(message=message)])


def wait_for_port(port: int, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("localhost", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"nothing listens on {port}")


@pytest.fixture(scope="session")
def backend():
    """Fresh test DB + a real bank MCP server over HTTP."""
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS agent_test WITH (FORCE)")
        conn.execute("CREATE DATABASE agent_test")
    mcp = subprocess.Popen([sys.executable, "-m", "bank_mcp.server", "--http", "--port", str(MCP_PORT)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for_port(MCP_PORT)
    yield
    mcp.terminate()
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS agent_test WITH (FORCE)")


@pytest.fixture(scope="module")
def client(backend):
    """In-process API (FastAPI TestClient)."""
    from fastapi.testclient import TestClient

    from app.api import create_app
    with TestClient(create_app(llm=FakeAnalyst())) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def api_url(backend):
    """The API served by a real uvicorn on a port — for the bot, which talks HTTP."""
    import uvicorn

    from app.api import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(llm=FakeAnalyst()), port=API_PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for_port(API_PORT)
    yield f"http://localhost:{API_PORT}"
    server.should_exit = True
    thread.join(timeout=10)
