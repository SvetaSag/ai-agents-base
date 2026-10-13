"""Settings, read from the environment (.env locally, `environment:` in docker compose)."""

import os

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("MODEL", "openai/gpt-4o-mini")
# agent memory + sessions live here
AGENT_DSN = os.getenv("AGENT_DSN", "postgresql://postgres:postgres@localhost:5434/agent")
# our bank MCP server, served over streamable HTTP (python -m bank_mcp.server --http)
BANK_MCP_URL = os.getenv("BANK_MCP_URL", "http://localhost:8001/mcp")
# the bot talks to the API, not to the database
API_URL = os.getenv("API_URL", "http://localhost:8080")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# optional allow-list: comma-separated Telegram user ids; empty = everyone
TELEGRAM_ALLOWED_USERS = {int(x) for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()}
