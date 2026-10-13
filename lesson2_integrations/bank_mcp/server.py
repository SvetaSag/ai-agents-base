"""Bank MCP server — read-only access to the Berka bank dataset in Postgres.

An MCP server exposes three kinds of things to any MCP client (an agent,
Claude Desktop, Cursor, MCP Inspector...):

  * TOOLS     — functions the MODEL decides to call      (list_tables, run_sql, ...)
  * RESOURCES — data the APPLICATION reads by URI        (bank://schema, ...)
  * PROMPTS   — ready-made prompt templates for the USER (analyze_account)

Run it:
    python -m bank_mcp.server            # stdio: the client starts us as a subprocess
    python -m bank_mcp.server --http     # streamable HTTP on :8001/mcp (docker, many clients)

Security of run_sql — the model writes arbitrary SQL, so we stack layers:
  1. privileges: the `mcp_reader` role may only SELECT (db/init.sql) — the core guarantee;
  2. parser: exactly ONE read-only SELECT statement (sqlglot) — no `;`, SET, COMMIT, DML;
  3. execution: our own READ ONLY transaction + SET LOCAL statement_timeout + a server-side
     cursor that fetches only max_rows rows (a million-row SELECT never reaches our memory).
Role-level defaults (read-only, timeout) are NOT a guarantee: a session can change them.

stdio rule: never print() — stdout IS the protocol channel. Logs go to stderr.
"""

import argparse
import os
from datetime import date
from decimal import Decimal

import psycopg
import sqlglot
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from psycopg import sql
from sqlglot import exp

load_dotenv()
DSN = os.getenv("BANK_DSN", "postgresql://mcp_reader:mcp_reader@localhost:5434/bank")
MAX_ROWS = 200
TIMEOUT_S = 15                  # per run_sql query
# anything that writes, changes settings or runs raw commands — forbidden anywhere in the tree
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
             exp.Command, exp.Set, exp.Into, exp.Lock)

mcp = FastMCP(
    "bank",
    instructions=(
        "Read-only access to an anonymised Czech retail bank (Berka dataset, 1993–1998). "
        "All amounts are in CZK. Start with list_tables / describe_table, then run_sql. "
        "For questions about one account use account_summary."
    ),
    # quiet by default: over stdio our stderr ends up in the client's output
    log_level=os.getenv("MCP_LOG_LEVEL", "WARNING"),
)


# ── helpers ─────────────────────────────────────────────────────────────────

async def fetch(query, params=None) -> tuple[list[str], list[tuple]]:
    """Run a query as the read-only role; return (column names, rows)."""
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute(query, params)
        columns = [d.name for d in cur.description] if cur.description else []
        return columns, await cur.fetchall()


def cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}" if value != value.to_integral() else str(int(value))
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def markdown_table(columns: list[str], rows: list[tuple]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


async def known_tables() -> list[str]:
    _, rows = await fetch("SELECT table_name FROM information_schema.tables "
                          "WHERE table_schema = 'public' ORDER BY table_name")
    return [r[0] for r in rows]


# ── TOOLS: the model calls these ────────────────────────────────────────────

@mcp.tool()
async def list_tables() -> str:
    """List all tables of the bank database with row counts and descriptions. Call this first."""
    lines = []
    for table in await known_tables():
        _, rows = await fetch(sql.SQL("SELECT count(*), obj_description({}::regclass) FROM {}")
                              .format(sql.Literal(table), sql.Identifier(table)))
        count, comment = rows[0]
        lines.append(f"- {table} ({count:,} rows): {comment or ''}")
    return "\n".join(lines)


@mcp.tool()
async def describe_table(table: str) -> str:
    """Show the columns of a table (name, type, meaning) and 3 sample rows. Use it before writing SQL.

    Args:
        table: Table name, e.g. "transactions".
    """
    if table not in await known_tables():
        return f"Error: unknown table '{table}'. Call list_tables to see the available ones."
    _, cols = await fetch(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod), col_description(a.attrelid, a.attnum) "
        "FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum", (table,))
    columns, sample = await fetch(sql.SQL("SELECT * FROM {} LIMIT 3").format(sql.Identifier(table)))
    described = "\n".join(f"- {name} ({type_}): {comment or ''}" for name, type_, comment in cols)
    return f"Table {table}\n\nColumns:\n{described}\n\nSample rows:\n{markdown_table(columns, sample)}"


def check_select(query: str) -> str | None:
    """Return why `query` is not allowed, or None if it is ONE read-only SELECT."""
    try:
        statements = [s for s in sqlglot.parse(query, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        return f"cannot parse the query: {str(exc).splitlines()[0]}"
    if len(statements) != 1:
        return f"exactly one statement is allowed, got {len(statements)}"
    if not isinstance(statements[0], exp.Query):            # SELECT / UNION / WITH … SELECT
        return f"only SELECT queries are allowed, got {statements[0].key.upper()}"
    bad = statements[0].find(*FORBIDDEN)
    if bad is not None:                                     # e.g. WITH d AS (DELETE …) SELECT …
        return f"{bad.key.upper()} is not allowed — the database is read-only"
    return None


async def fetch_limited(query: str, limit: int) -> tuple[list[str], list[tuple]]:
    """Run ONE SELECT in a read-only transaction with a timeout; fetch at most `limit` rows."""
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        await conn.set_read_only(True)                      # our transaction: BEGIN READ ONLY
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = '{TIMEOUT_S}s'")
            async with conn.cursor(name="run_sql") as cur:  # server-side cursor: DECLARE … FETCH
                await cur.execute(query)
                rows = await cur.fetchmany(limit)
                return [d.name for d in cur.description], rows


@mcp.tool()
async def run_sql(query: str, max_rows: int = 50) -> str:
    """Run a read-only SQL query (PostgreSQL dialect) and return the result as a table.

    Only ONE SELECT (or WITH ... SELECT) statement per call. Always aggregate in SQL
    (COUNT, SUM, AVG, GROUP BY) instead of fetching raw rows; add ORDER BY + LIMIT for
    top-N questions. Queries are cancelled after 15 seconds.

    Args:
        query: A single SELECT (or WITH ... SELECT) statement.
        max_rows: How many result rows to return (1-200).
    """
    statement = query.strip().rstrip(";")
    problem = check_select(statement)
    if problem:
        return f"Error: {problem}."
    max_rows = max(1, min(max_rows, MAX_ROWS))
    try:
        columns, rows = await fetch_limited(statement, max_rows + 1)   # +1: are there more?
    except psycopg.errors.QueryCanceled:
        return f"SQL error: the query took longer than {TIMEOUT_S} s — aggregate more or add filters."
    except psycopg.Error as exc:  # the model reads this and fixes its SQL
        return f"SQL error: {exc}".strip()
    more = len(rows) > max_rows
    note = f"\n\n(first {max_rows} rows; there are more)" if more else f"\n\n({len(rows)} rows)"
    return markdown_table(columns, rows[:max_rows]) + note


@mcp.tool()
async def account_summary(account_id: int) -> str:
    """Everything about one account in a single call: owner and users, district, current
    balance, turnover, loans and cards. Prefer this over SQL for questions about one account.

    Args:
        account_id: The account id, e.g. 2378.
    """
    _, acc = await fetch(
        "SELECT a.account_id, a.opened_on, a.statement_frequency, d.name, d.region "
        "FROM accounts a JOIN districts d USING (district_id) WHERE a.account_id = %s", (account_id,))
    if not acc:
        return f"Error: account {account_id} not found."
    _, people = await fetch(
        "SELECT dp.role, c.client_id, c.gender, c.birth_date FROM dispositions dp "
        "JOIN clients c USING (client_id) WHERE dp.account_id = %s ORDER BY dp.role", (account_id,))
    _, stats = await fetch(
        "SELECT count(*), min(trans_date), max(trans_date), "
        "sum(amount) FILTER (WHERE direction = 'credit'), sum(amount) FILTER (WHERE direction = 'debit'), "
        "(SELECT balance FROM transactions WHERE account_id = %s ORDER BY trans_date DESC, trans_id DESC LIMIT 1) "
        "FROM transactions WHERE account_id = %s", (account_id, account_id))
    loan_cols, loans = await fetch(
        "SELECT granted_on, amount, duration_months, monthly_payment, status FROM loans WHERE account_id = %s",
        (account_id,))
    card_cols, cards = await fetch(
        "SELECT cd.card_type, cd.issued_on FROM cards cd JOIN dispositions dp USING (disp_id) "
        "WHERE dp.account_id = %s", (account_id,))

    _, opened, freq, district, region = acc[0]
    count, first, last, money_in, money_out, balance = stats[0]
    owners = ", ".join(f"{role} #{cid} ({g}, born {cell(b)})" for role, cid, g, b in people)
    return "\n".join([
        f"Account {account_id}: opened {cell(opened)}, branch in {district} ({region}), statements {freq}",
        f"People: {owners}",
        f"Transactions: {count} from {cell(first)} to {cell(last)}",
        f"Money in: {cell(money_in)} CZK, money out: {cell(money_out)} CZK, current balance: {cell(balance)} CZK",
        "Loans:\n" + (markdown_table(loan_cols, loans) if loans else "none"),
        "Cards:\n" + (markdown_table(card_cols, cards) if cards else "none"),
    ])


# ── RESOURCES: the application reads these by URI ───────────────────────────

@mcp.resource("bank://schema", mime_type="text/markdown")
async def schema() -> str:
    """The whole database schema with descriptions — handy to put into a system prompt."""
    parts = []
    for table in await known_tables():
        parts.append(await describe_table(table))
    return "\n\n---\n\n".join(parts)


@mcp.resource("bank://accounts/{account_id}/statement", mime_type="text/markdown")
async def statement(account_id: int) -> str:
    """The last 20 transactions of an account (a resource TEMPLATE: the URI has a parameter)."""
    columns, rows = await fetch(
        "SELECT trans_date, direction, operation, amount, balance, category FROM transactions "
        "WHERE account_id = %s ORDER BY trans_date DESC, trans_id DESC LIMIT 20", (int(account_id),))
    return markdown_table(columns, rows) if rows else f"No transactions for account {account_id}."


# ── PROMPTS: ready-made instructions the user can pick ──────────────────────

@mcp.prompt()
def analyze_account(account_id: int) -> str:
    """Ask the agent for a short financial portrait of one account."""
    return (
        f"Проанализируй банковский счёт {account_id}. Сначала вызови account_summary, "
        f"при необходимости уточни через run_sql (например, траты по категориям). "
        f"Дай краткий портрет клиента: кто владелец, обороты, баланс, кредиты, на что уходят деньги. "
        f"Все суммы в кронах (CZK). Ответь по-русски, 5–7 пунктов."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bank MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = args.port
        # DNS-rebinding protection: accept only these Host headers ("mcp" = the docker compose service name)
        hosts = os.getenv("MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,mcp").split(",")
        mcp.settings.transport_security = TransportSecuritySettings(allowed_hosts=[f"{h}:*" for h in hosts])
        mcp.run(transport="streamable-http")   # → http://<host>:8001/mcp
    else:
        mcp.run()                              # stdio


if __name__ == "__main__":
    main()
