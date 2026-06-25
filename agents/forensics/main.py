"""Data Forensics — LangGraph hosted agent that investigates the energy Lakehouse
using natural language via the Databricks Genie MCP server.

Exposes the Foundry Responses protocol. The agent calls the Genie MCP tools
(query + poll) to translate investigator questions into governed SQL over the
Unity Catalog tables and returns grounded answers.

Run locally:  python main.py   (http://localhost:8088/responses)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent  # noqa: E402
from langchain_azure_ai.agents.hosting import ResponsesHostServer  # noqa: E402

from shared.model import build_chat_model  # noqa: E402
from shared.observability import enable_tracing  # noqa: E402
from shared.tools.genie_mcp import get_genie_tools  # noqa: E402

enable_tracing("forensics")

INSTRUCTIONS = """You are an Energy Fraud Data Forensics agent.

You investigate smart-meter readings and customer profiles stored in the
Lakehouse using the Genie tools. Genie runs asynchronously: call the query tool
to start a question, then call the poll tool until the response is complete. Do
not stop after a few seconds — keep polling until you receive the answer.

Translate the investigator's natural-language question into a Genie query,
report the findings clearly, and cite the figures (consumption, baseline ratios,
meter trust, fraud history) returned by Genie.
"""

# Genie MCP tools are loaded at startup (the hosted runtime has network + token).
_genie_tools = asyncio.run(get_genie_tools())

graph = create_agent(
    build_chat_model(),
    tools=_genie_tools,
    system_prompt=INSTRUCTIONS,
)


def main() -> None:
    port = int(os.environ.get("PORT", "8088"))
    ResponsesHostServer(graph).run(port=port)


if __name__ == "__main__":
    main()
