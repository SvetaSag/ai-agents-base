"""Analyst agent — the bank analyst from lesson 2, published as an A2A agent.

Inside: the same LangGraph graph (agent ⇄ tools) with the bank tools from our MCP
server. Outside: the A2A protocol — any other agent can find out what it can do
(the agent card) and ask it a question, without knowing anything about its
model, tools or code.

    uv run python mcp_server.py        # first, in another terminal
    uv run python analyst_agent.py     → http://localhost:8102

    GET  /.well-known/agent-card.json   the agent card ("business card")
    POST /                              JSON-RPC: SendMessage, GetTask, ...
"""

import logging
import os
from contextlib import asynccontextmanager, contextmanager, nullcontext

import httpx
import uvicorn
from a2a.helpers.proto_helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from starlette.applications import Starlette

load_dotenv()
PORT = 8102
MCP_URL = os.getenv("MCP_URL", "http://localhost:8101/mcp")
log = logging.getLogger("analyst")          # only OUR lines in this terminal, libraries stay quiet
log.setLevel(logging.INFO)
log.propagate = False                       # the SDKs put their own handler on the root logger
log.addHandler(logging.StreamHandler())
log.handlers[0].setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

SYSTEM = ("Ты аналитик данных банка. Отвечай по-русски, кратко, фактами и цифрами. "
          "Данные — чешский банк 1993–1998, суммы в кронах (CZK). Структуру базы узнавай через "
          "list_tables и describe_table, данные — через run_sql. Ты даёшь только факты: "
          "решений (выдавать ли кредит и т. п.) не принимаешь.")

# ── 1. the agent card: what other agents see ────────────────────────────────────
CARD = AgentCard(
    name="Bank analyst",
    description="Отвечает на вопросы по данным банка: счета, обороты, балансы, кредиты, клиенты.",
    version="1.0",
    supported_interfaces=[AgentInterface(url=f"http://localhost:{PORT}/", protocol_binding="JSONRPC")],
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[AgentSkill(
        id="bank-data",
        name="Данные банка",
        description="Факты и цифры по базе банка: SQL-аналитика по счетам, транзакциям, кредитам.",
        tags=["bank", "sql", "analytics"],
        examples=["Какой средний месячный приход на счёт 2378 за 1998 год?",
                  "Есть ли у счёта 2378 кредиты и в каком они статусе?"],
    )],
)


# ── 2. the agent itself: the graph from lesson 2 ────────────────────────────────
def build_graph(llm, tools):
    """agent ⇄ tools, as in lesson 2 — but WITHOUT memory.

    A sub-agent gets self-contained questions ("account 2378, income in 1998") and answers each
    on its own. The conversation with the user is remembered by the caller (the risk manager).
    """
    llm_with_tools = llm.bind_tools(tools)

    async def agent(state: MessagesState) -> dict:
        return {"messages": [await llm_with_tools.ainvoke([("system", SYSTEM), *state["messages"]])]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()


def langfuse_client():
    """Langfuse client if its keys are set and the server answers, else None (lesson part 3)."""
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    from langfuse import get_client
    client = get_client()
    try:
        return client if client.auth_check() else None
    except Exception:
        return None


@contextmanager
def caller_span(trace_id: str, parent_span_id: str):
    """Make a step of ANOTHER process (the caller's span) the parent of what we trace here.

    Standard OpenTelemetry: the ids came with the A2A message, we put them into the
    current context, and Langfuse attaches our spans under that step of that trace.
    """
    parent = otel_trace.NonRecordingSpan(otel_trace.SpanContext(
        trace_id=int(trace_id, 16), span_id=int(parent_span_id, 16),
        is_remote=True, trace_flags=otel_trace.TraceFlags(otel_trace.TraceFlags.SAMPLED)))
    token = otel_context.attach(otel_trace.set_span_in_context(parent))
    try:
        yield
    finally:
        otel_context.detach(token)


# ── 3. the A2A wrapper: request in → graph → answer out ─────────────────────────
class AnalystExecutor(AgentExecutor):
    graph = None                                         # set at startup (needs the MCP tools)
    langfuse = None

    async def execute(self, context: RequestContext, event_queue) -> None:
        question = context.get_user_input()
        metadata = MessageToDict(context.message.metadata)   # extra fields sent by the caller

        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)            # the task exists: state "submitted"
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()                           # state "working"

        log.info("📨 вопрос: %s", question)
        try:
            answer = await self.answer(question, metadata)
        except Exception as error:                           # e.g. the LLM provider is down
            log.info("❌ ошибка: %s", error)
            await updater.failed(updater.new_agent_message([new_text_part(f"Ошибка аналитика: {error}")]))
            return                                           # state "failed", with the reason
        log.info("📤 ответ: %s", answer.replace("\n", " ")[:300])

        await updater.add_artifact([new_text_part(answer)], name="answer")
        await updater.complete()                             # state "completed"

    async def answer(self, question: str, metadata: dict) -> str:
        if self.langfuse is None:                            # no tracing
            result = await self.graph.ainvoke({"messages": [("user", question)]})
            return result["messages"][-1].text

        # with tracing (part 3). If the caller sent its trace id (part 4), our steps go INTO its trace.
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler
        if "trace_id" in metadata and "parent_span_id" in metadata:   # the caller is traced → continue ITS trace
            parent, attributes = caller_span(metadata["trace_id"], metadata["parent_span_id"]), {}
        else:                            # nobody upstream → our own trace, named "analyst"
            parent, attributes = nullcontext(), {"trace_name": "analyst"}
        if "session_id" in metadata:     # the user's session: links our trace to the caller's in Langfuse
            attributes["session_id"] = metadata["session_id"]
        with parent, propagate_attributes(**attributes), \
                self.langfuse.start_as_current_observation(name="analyst", as_type="agent", input=question) as span:
            result = await self.graph.ainvoke({"messages": [("user", question)]}, {"callbacks": [CallbackHandler()]})
            span.update(output=result["messages"][-1].text)
        return result["messages"][-1].text

    async def cancel(self, context: RequestContext, event_queue) -> None:
        raise NotImplementedError("cancel is not supported")


executor = AnalystExecutor()


@asynccontextmanager
async def lifespan(app):
    """At startup: take the tools from the MCP server and build the graph."""
    client = MultiServerMCPClient({"bank": {"transport": "streamable_http", "url": MCP_URL}})
    tools = await client.get_tools()
    llm = ChatOpenAI(model=os.getenv("MODEL", "openai/gpt-4o-mini"), base_url="https://openrouter.ai/api/v1",
                     api_key=os.getenv("OPENROUTER_API_KEY"))
    executor.graph = build_graph(llm, tools)
    executor.langfuse = langfuse_client()
    log.info("analyst is ready → http://localhost:%s  (MCP tools: %s, Langfuse: %s)",
             PORT, [tool.name for tool in tools], "on" if executor.langfuse else "off")
    yield
    if executor.langfuse:
        executor.langfuse.flush()


handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=CARD)
app = Starlette(routes=create_agent_card_routes(CARD) + create_jsonrpc_routes(handler, "/"), lifespan=lifespan)

if __name__ == "__main__":
    try:
        httpx.get(MCP_URL, timeout=3)                    # the tools live there — is it up?
    except httpx.ConnectError:
        raise SystemExit(f"❌ MCP-сервер не запущен ({MCP_URL}). Сначала: uv run python mcp_server.py") from None
    uvicorn.run(app, port=PORT, log_level="warning")
