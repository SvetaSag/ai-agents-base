"""The agent: the same LangGraph graph as in the notebooks, its tools come from the bank MCP server.

Differences from the notebooks:
  * memory is a Postgres checkpointer (passed in), so conversations survive restarts;
  * the system prompt is added at call time, NOT stored in the history;
  * an empty answer (some models do that now and then) is retried once.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

NUDGE = "Ответь пользователю по результатам инструментов выше."

SYSTEM = """Ты аналитик банка. Отвечай по-русски, кратко и с цифрами.
Данные — обезличенный чешский банк, 1993–1998, все суммы в кронах (CZK).
Для вопросов про один счёт вызывай account_summary. Для аналитики пиши SQL (PostgreSQL)
и вызывай run_sql; агрегируй в SQL, не выгружай сырые строки.

Схема базы:
{schema}"""


async def load_bank_tools(url: str) -> tuple[list, str]:
    """Connect to the bank MCP server: its tools + the database schema (an MCP resource)."""
    client = MultiServerMCPClient({"bank": {"transport": "streamable_http", "url": url}})
    tools = await client.get_tools()
    schema = (await client.get_resources("bank", uris=["bank://schema"]))[0].as_string()
    return tools, schema


def build_graph(llm, tools: list, schema: str, checkpointer):
    """agent ⇄ tools, exactly as in 02_mcp_langgraph.ipynb."""
    system = SystemMessage(SYSTEM.format(schema=schema))
    llm_with_tools = llm.bind_tools(tools)

    async def agent(state: MessagesState) -> dict:
        messages = [system, *state["messages"]]
        response = await llm_with_tools.ainvoke(messages)
        if not response.tool_calls and not response.text.strip():      # empty answer → ask once more
            response = await llm_with_tools.ainvoke([*messages, HumanMessage(NUDGE)])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


async def chat(graph, session_id: int, text: str) -> dict:
    """One message → the answer and the tools the agent called. Session number = thread_id."""
    config = {"configurable": {"thread_id": str(session_id)}}
    before = len((await graph.aget_state(config)).values.get("messages", []))
    result = await graph.ainvoke({"messages": [HumanMessage(text)]}, config)
    new_messages = result["messages"][before:]                           # only this turn
    tools = [{"name": call["name"], "args": call["args"]}
             for message in new_messages if message.type == "ai" for call in message.tool_calls]
    return {"answer": result["messages"][-1].text, "tools": tools}


async def history(graph, session_id: int) -> list[dict]:
    """The saved conversation for the web page: questions and answers (tool steps folded in)."""
    state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
    turns, tools = [], []
    for message in state.values.get("messages", []):
        if message.type == "human":
            turns.append({"role": "user", "content": message.text})
        elif message.type == "ai" and message.tool_calls:
            tools += [{"name": call["name"], "args": call["args"]} for call in message.tool_calls]
        elif message.type == "ai":
            turns.append({"role": "assistant", "content": message.text, "tools": tools})
            tools = []
    return turns
