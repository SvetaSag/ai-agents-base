"""MCP server with the bank tools — the same three tools as in lesson 2 (01_mcp_server_client).

Started from a terminal and listens over HTTP, so any number of agents can use it:

    uv run python mcp_server.py          → http://localhost:8101/mcp

Every tool call is printed here, so during the lesson this terminal shows
which SQL the agents actually run.
"""

import logging
import os

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
DSN = os.getenv("BANK_DSN", "postgresql://mcp_reader:mcp_reader@localhost:5435/bank")   # read-only role
PORT = 8101

log = logging.getLogger("bank-mcp")         # only OUR lines in this terminal, libraries stay quiet
log.setLevel(logging.INFO)
log.propagate = False                       # the SDKs put their own handler on the root logger
log.addHandler(logging.StreamHandler())
log.handlers[0].setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
mcp = FastMCP("bank", port=PORT, log_level="WARNING")


def query(sql: str, params=None) -> str:
    """Run SQL and return the result as text: a header line, then one line per row (max 50).

    A database error is returned as text too — the model reads it and fixes its query.
    """
    try:
        with psycopg.connect(DSN) as conn:
            cursor = conn.execute(sql, params)
            lines = [" | ".join(column.name for column in cursor.description)]
            lines += [" | ".join(str(value) for value in row) for row in cursor.fetchmany(50)]
        return "\n".join(lines)
    except psycopg.Error as error:
        log.info("   ↳ SQL error: %s", str(error).splitlines()[0])
        return f"SQL error: {error}"


@mcp.tool()
def list_tables() -> str:
    """List the tables of the bank database with a short description of each."""
    log.info("🔧 list_tables()")
    return query("SELECT relname AS table_name, obj_description(oid) AS description "
                 "FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1")


@mcp.tool()
def describe_table(table: str) -> str:
    """Show the columns of one table: name, type and what the column means."""
    log.info("🔧 describe_table(%s)", table)
    return query("SELECT column_name, data_type, col_description(%s::regclass, ordinal_position) AS meaning "
                 "FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                 (table, table))


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run a read-only SQL query (PostgreSQL) and return up to 50 rows."""
    log.info("🔧 run_sql:\n%s", sql)
    return query(sql)


if __name__ == "__main__":
    log.info("bank MCP server → http://localhost:%s/mcp", PORT)
    mcp.run(transport="streamable-http")
