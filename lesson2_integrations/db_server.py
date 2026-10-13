"""A minimal MCP server over the bank database (written by 01_mcp_server_client.ipynb)."""

import os
import sys

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
DSN = os.getenv("BANK_DSN")              # the read-only role mcp_reader
mcp = FastMCP("bank-lite", log_level="WARNING")


def query(sql: str, params=None) -> str:
    """Run SQL and return the result as text: a header line, then one line per row (max 50)."""
    with psycopg.connect(DSN) as conn:
        cursor = conn.execute(sql, params)
        lines = [" | ".join(column.name for column in cursor.description)]
        lines += [" | ".join(str(value) for value in row) for row in cursor.fetchmany(50)]
    return "\n".join(lines)


@mcp.tool()
def list_tables() -> str:
    """List the tables of the bank database with a short description of each."""
    return query("SELECT relname AS table_name, obj_description(oid) AS description "
                 "FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1")


@mcp.tool()
def describe_table(table: str) -> str:
    """Show the columns of one table: name, type and what the column means."""
    return query("SELECT column_name, data_type, col_description(%s::regclass, ordinal_position) AS meaning "
                 "FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                 (table, table))


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run a read-only SQL query (PostgreSQL) and return up to 50 rows."""
    try:
        return query(sql)
    except psycopg.Error as error:
        return f"SQL error: {error}"     # the model reads the error and fixes its query


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.port = 8011
        mcp.run(transport="streamable-http")   # a network service: http://localhost:8011/mcp
    else:
        mcp.run()                              # stdio: the client starts us as a subprocess
