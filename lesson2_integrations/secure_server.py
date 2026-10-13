"""The bank tools over HTTP — only for clients that send the right token."""

import os
import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from db_server import describe_table, list_tables, run_sql   # the tools from part 1, unchanged

TOKEN = os.environ["MCP_TOKEN"]                               # the secret, given at start
URL = "http://localhost:8012"


class CheckToken(TokenVerifier):
    """Called on every request with the token from the header `Authorization: Bearer <token>`."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, TOKEN):              # constant-time compare
            return AccessToken(token=token, client_id="student", scopes=[])
        return None                                           # → 401 Unauthorized


mcp = FastMCP(
    "bank-secure", port=8012, log_level="WARNING",
    token_verifier=CheckToken(),
    auth=AuthSettings(issuer_url=URL, resource_server_url=f"{URL}/mcp", required_scopes=[],
                      validate_token_resource=False),         # our verifier checks the token itself
)
mcp.tool()(list_tables)
mcp.tool()(describe_table)
mcp.tool()(run_sql)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")                      # http://localhost:8012/mcp
