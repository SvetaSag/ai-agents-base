"""The demo MCP server from 00_mcp_hello.ipynb as a standalone program (stdio)."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo", log_level="WARNING")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@mcp.tool()
def get_weather(city: str) -> str:
    """Current weather in a city (fake data)."""
    return f"В городе {city} +18°C, солнечно"


if __name__ == "__main__":
    mcp.run()   # stdio: requests come on stdin, answers go to stdout
