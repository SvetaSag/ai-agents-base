-- Runs ONCE, when the Postgres volume is created. The data itself: scripts/load_berka.py.
-- The MCP server reads the bank as `mcp_reader`, which may only SELECT.
CREATE ROLE mcp_reader LOGIN PASSWORD 'mcp_reader';
ALTER ROLE mcp_reader SET default_transaction_read_only = on;
ALTER ROLE mcp_reader SET statement_timeout = '15s';
GRANT CONNECT ON DATABASE bank TO mcp_reader;
GRANT USAGE ON SCHEMA public TO mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_reader;
