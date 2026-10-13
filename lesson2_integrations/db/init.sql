-- Runs ONCE, when the Postgres volume is created for the first time.
--   bank  — the dataset (filled by scripts/load_berka.py); the MCP server reads it
--   agent — the agent's memory: LangGraph checkpoints + chat sessions (lesson part 5)
CREATE DATABASE agent;

-- The MCP server gets its own role that can only READ the bank data.
-- PRIVILEGES are the real guarantee: the role has SELECT and nothing else, so even
-- `BEGIN READ WRITE; DELETE ...` fails. The two settings below are only DEFAULTS —
-- a session can override them; run_sql enforces its own read-only txn + timeout.
CREATE ROLE mcp_reader LOGIN PASSWORD 'mcp_reader' CONNECTION LIMIT 20;
ALTER ROLE mcp_reader SET default_transaction_read_only = on;
ALTER ROLE mcp_reader SET statement_timeout = '15s';
GRANT CONNECT ON DATABASE bank TO mcp_reader;
GRANT USAGE ON SCHEMA public TO mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_reader;
