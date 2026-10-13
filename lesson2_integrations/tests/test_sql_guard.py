"""run_sql must survive a model (or a prompt injection) that tries to write, stall or flood.

Each attack below passes a naive "starts with SELECT" check. Calls run_sql directly
against the real database (needs `docker compose up -d postgres` with the dataset).
"""

import asyncio
import time

import psycopg
import pytest

from bank_mcp import server

ADMIN = "postgresql://postgres:postgres@localhost:5434/bank"

ATTACKS = {
    "SELECT 1; DELETE FROM loans": "exactly one statement",
    "SELECT 1; COMMIT; BEGIN READ WRITE; DELETE FROM loans": "exactly one statement",
    "SELECT 1; SET statement_timeout = 0; SELECT pg_sleep(60)": "exactly one statement",
    "WITH d AS (DELETE FROM loans RETURNING *) SELECT count(*) FROM d": "DELETE is not allowed",
    "SELECT * INTO loans_copy FROM loans": "INTO is not allowed",
    "SELECT * FROM loans FOR UPDATE": "LOCK is not allowed",
    "DELETE FROM loans": "only SELECT",
    "COPY loans TO '/tmp/x'": "only SELECT",
    "SELECT pg_read_file('/etc/passwd')": "permission denied",
}


def run(query: str, max_rows: int = 3) -> str:
    return asyncio.run(server.run_sql(query, max_rows))


def loans_count() -> int:
    with psycopg.connect(ADMIN) as conn:
        return conn.execute("SELECT count(*) FROM loans").fetchone()[0]


@pytest.mark.parametrize("query, expected", ATTACKS.items())
def test_attack_is_refused(query, expected):
    assert expected in run(query)


def test_data_is_untouched():
    assert loans_count() == 682


@pytest.mark.parametrize("query", [
    "SELECT 1; COMMIT; BEGIN READ WRITE; CREATE TEMP TABLE x(a int)",
    "WITH d AS (DELETE FROM loans RETURNING *) SELECT count(*) FROM d",
    "SELECT 1; SET statement_timeout = 0; SELECT 2",
    "DELETE FROM loans",
])
def test_execution_layer_holds_even_without_the_parser(query):
    with pytest.raises(psycopg.Error):
        asyncio.run(server.fetch_limited(query, 3))


def test_timeout_cannot_be_lifted_from_inside_the_query(monkeypatch):
    monkeypatch.setattr(server, "TIMEOUT_S", 1)
    started = time.time()
    result = run("SELECT set_config('statement_timeout', '0', true), pg_sleep(30)")
    assert "longer than 1 s" in result and time.time() - started < 5


def test_only_max_rows_are_fetched():
    assert run("SELECT * FROM transactions", 2).endswith("(first 2 rows; there are more)")
    assert run("SELECT 1 UNION ALL SELECT 2", 5).endswith("(2 rows)")


@pytest.mark.parametrize("query", [   # real analytics must NOT be rejected
    "SELECT DISTINCT ON (account_id) account_id, balance FROM transactions "
    "ORDER BY account_id, trans_date DESC, trans_id DESC LIMIT 3",
    "SELECT EXTRACT(year FROM trans_date)::int AS y, count(*) FILTER (WHERE direction = 'debit') "
    "FROM transactions GROUP BY 1 ORDER BY 1",
    "WITH x AS (SELECT account_id, row_number() OVER (PARTITION BY account_id ORDER BY amount DESC) r "
    "FROM loans) SELECT count(*) FROM x WHERE r = 1",
    "SELECT status, percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM loans GROUP BY status",
    "SELECT d.region, avg(l.amount) FROM loans l JOIN accounts a USING (account_id) "
    "JOIN districts d ON d.district_id = a.district_id WHERE d.name ILIKE 'pr%' GROUP BY 1;",
])
def test_real_analytics_passes(query):
    result = run(query)
    assert not result.startswith(("Error", "SQL error")), result
