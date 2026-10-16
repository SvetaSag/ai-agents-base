"""Risk manager agent — decides on loans by asking the analyst agent over A2A.

The same agent that 02_two_agents.ipynb builds step by step; notebooks 03 and 04
import it from here. It has NO access to the database: for facts it asks the
analyst agent (http://localhost:8102), and it knows the loan policy itself.

Memory: the risk manager remembers the conversation with the user (thread_id =
the user's session). The analyst has no memory — it only gets the session id
in the A2A metadata, so that Langfuse can group both agents' traces.
"""

import os
import uuid

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_artifact_text, get_message_text, new_text_part
from a2a.types import Message, Role, SendMessageRequest, TaskState
from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

ANALYST_URL = os.getenv("ANALYST_URL", "http://localhost:8102")

POLICY = """Ты риск-менеджер банка. Решаешь, можно ли выдать кредит клиенту (счёту).
Доступа к базе у тебя нет: все факты о счёте спрашивай у аналитика (ask_analyst) — конкретными
вопросами с номером счёта и периодом. Платёж считай инструментом loan_payment.

Кредитная политика (учебная). Суммы в кронах (CZK), ставка 8% годовых:
1. Ежемесячный платёж по новому кредиту — не больше 30% среднего месячного прихода на счёт за 1998 год.
2. Если у счёта есть кредит в статусе running_in_debt или finished_default — отказ. Кредитную
   историю проверяй за ВСЁ время, а не только за 1998 год: старый кредит тоже считается.
3. Средний баланс счёта за 1998 год должен быть не меньше одного ежемесячного платежа.

Ответ: решение ОДОБРИТЬ или ОТКАЗАТЬ, затем коротко по каждому пункту политики — цифры и вывод."""


async def send_to_analyst(question: str, metadata: dict | None = None) -> str:
    """One A2A request: send a message to the analyst agent, return the text of its answer."""
    client = await create_client(ANALYST_URL, client_config=ClientConfig(
        streaming=False, httpx_client=httpx.AsyncClient(timeout=300)))   # the analyst may think a while
    message = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()), parts=[new_text_part(question)])
    if metadata:
        message.metadata.update(metadata)                # extra fields, e.g. the trace id (part 4)
    try:
        async for event in client.send_message(SendMessageRequest(message=message)):
            task = event.task
            if task.status.state == TaskState.TASK_STATE_COMPLETED:
                return get_artifact_text(task.artifacts[0])          # the answer
            return f"Аналитик не ответил: {get_message_text(task.status.message)}"   # e.g. failed
    finally:
        await client.close()


@tool
async def ask_analyst(question: str, config: RunnableConfig) -> str:
    """Ask the bank's analyst agent a factual question about the bank data (accounts, transactions,
    balances, loans). Ask concrete questions with the account number and the period."""
    session_id = config.get("configurable", {}).get("thread_id")    # our conversation = the user's session
    print(f"   📨 → аналитику: {question}")
    # we pass the session id only as a label for Langfuse — the analyst does not remember anything
    answer = await send_to_analyst(question, {"session_id": session_id} if session_id else None)
    print(f"   📨 ← аналитик: {answer[:300]}")
    return answer


@tool
def loan_payment(amount: float, months: int, annual_rate_percent: float = 8.0) -> str:
    """Monthly payment of an annuity loan: amount in CZK, term in months, annual rate in percent."""
    rate = annual_rate_percent / 100 / 12
    payment = amount * rate / (1 - (1 + rate) ** -months)
    return f"{payment:.2f} CZK в месяц"


def build_risk_agent(llm, ask_tool=ask_analyst):
    """The risk manager: a LangGraph agent (create_agent) with two tools and its own memory."""
    return create_agent(llm, [ask_tool, loan_payment], system_prompt=POLICY, checkpointer=InMemorySaver())
