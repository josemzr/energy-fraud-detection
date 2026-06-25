"""Genie MCP integration — exposes the Databricks Genie Space (NL-to-SQL over the
energy Lakehouse) to LangGraph agents as MCP tools.

Connects to the Databricks managed Genie MCP server:
  https://<workspace-hostname>/api/2.0/mcp/genie/<genie_space_id>

For local/dev a Databricks token (PAT or service principal) is used. In a
production Foundry hosted agent, prefer OAuth on-behalf-of authentication.

Environment:
  DATABRICKS_WORKSPACE_HOSTNAME   e.g. adb-7405619936090888.8.azuredatabricks.net
  GENIE_SPACE_ID                  the Genie Space id
  GENIE_MCP_TOKEN                 (or DATABRICKS_TOKEN / MODEL_SERVING_TOKEN) bearer token
"""

from __future__ import annotations

import os

from langchain_mcp_adapters.client import MultiServerMCPClient


def _genie_mcp_url() -> str:
    hostname = os.environ["DATABRICKS_WORKSPACE_HOSTNAME"].rstrip("/")
    space_id = os.environ["GENIE_SPACE_ID"]
    return f"https://{hostname}/api/2.0/mcp/genie/{space_id}"


def _bearer_token() -> str:
    token = (
        os.environ.get("GENIE_MCP_TOKEN")
        or os.environ.get("DATABRICKS_TOKEN")
        or os.environ.get("MODEL_SERVING_TOKEN")
    )
    if not token:
        raise RuntimeError(
            "Set GENIE_MCP_TOKEN (or DATABRICKS_TOKEN / MODEL_SERVING_TOKEN) to authenticate to the Genie MCP server."
        )
    return token


def genie_mcp_client() -> MultiServerMCPClient:
    """Return a MultiServerMCPClient configured for the Genie MCP server."""
    return MultiServerMCPClient(
        {
            "genie": {
                "transport": "streamable_http",
                "url": _genie_mcp_url(),
                "headers": {"Authorization": f"Bearer {_bearer_token()}"},
            }
        }
    )


async def get_genie_tools() -> list:
    """Load the Genie MCP tools as LangChain tools for use in a LangGraph agent."""
    client = genie_mcp_client()
    return await client.get_tools()
