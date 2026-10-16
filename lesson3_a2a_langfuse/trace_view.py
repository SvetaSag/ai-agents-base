"""Print a Langfuse trace as a tree right in the notebook (the same tree the Langfuse UI shows)."""

import time

from langfuse import get_client

AGENTS = ("risk-manager", "analyst")                       # our root spans
ICONS = {"AGENT": "🤖", "GENERATION": "🧠", "TOOL": "🔧", "SPAN": "📨", "CHAIN": "·"}


def fetch_trace(trace_id: str, timeout: float = 30):
    """Langfuse stores traces asynchronously — wait until the trace is complete."""
    langfuse = get_client()
    langfuse.flush()
    deadline, seen = time.time() + timeout, -1
    while time.time() < deadline:
        try:
            trace = langfuse.api.trace.get(trace_id)
            if len(trace.observations) == seen and seen > 0:      # nothing new arrived → done
                return trace
            seen = len(trace.observations)
        except Exception:                                         # not ingested yet
            pass
        time.sleep(3)
    return langfuse.api.trace.get(trace_id)


def print_trace(trace_id: str) -> None:
    """The trace as an indented tree: what ran inside what, how long it took, how many tokens."""
    trace = fetch_trace(trace_id)
    children: dict[str | None, list] = {}                         # parent id → its steps, in time order
    ids = {o.id for o in trace.observations}
    for o in sorted(trace.observations, key=lambda o: o.start_time):
        parent = o.parent_observation_id if o.parent_observation_id in ids else None
        children.setdefault(parent, []).append(o)

    tokens_by_agent: dict[str, int] = {}

    def show(o, level: int, agent: str) -> None:
        agent = o.name if o.name in AGENTS else agent              # which of our agents we are inside
        if o.name != "tools_condition":                           # graph plumbing, not interesting
            details = [f"{o.latency:.1f} s"] if o.latency is not None else []
            if o.type == "GENERATION" and o.usage:
                details.append(f"{o.usage.total} токенов")
                tokens_by_agent[agent] = tokens_by_agent.get(agent, 0) + o.usage.total
            line = f"{'   ' * level}{ICONS.get(o.type, '·')} {o.name}"
            print(f"{line:<55} {' · '.join(details)}")
        for child in children.get(o.id, []):
            show(child, level + 1, agent)

    for root in children.get(None, []):
        show(root, 0, "?")
    tokens = f"токенов: {sum(tokens_by_agent.values())}"
    if set(tokens_by_agent) - {"?"}:                               # our agents inside → split by agent
        tokens += f" (по агентам: {tokens_by_agent})"
    print(f"\nвсего: {trace.latency:.1f} s · шагов: {len(trace.observations)} · {tokens}")
