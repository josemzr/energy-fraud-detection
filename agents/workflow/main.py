"""Host the fraud detection workflow (LangGraph graph) as a Foundry hosted agent.

The workflow consumes a structured meter reading + customer profile and runs the
customer_data -> risk_analyzer -> (compliance_report | fraud_alert) flow. It uses
the Invocations protocol because the input is a structured reading, not a chat
message.

Request body:
  {"reading": { "consumption_kwh": 1300, "baseline_consumption_kwh": 450, ... }}

Run locally:  python main.py   (http://localhost:8088/invocations)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from starlette.requests import Request  # noqa: E402

from langchain_azure_ai.agents.hosting import InvocationsHostServer  # noqa: E402

from shared.observability import enable_tracing  # noqa: E402

enable_tracing("workflow")

from graph import graph  # noqa: E402


class WorkflowHostServer(InvocationsHostServer):
    """Maps the structured reading request onto the workflow graph state."""

    async def parse_request(self, request: Request) -> tuple[str, bool]:
        data = await request.json()
        reading = data.get("reading", data)
        stream = bool(data.get("stream", False))
        # Carry the reading as a JSON string; build_input reconstructs the state.
        return json.dumps(reading), stream

    def build_input(self, text: str) -> dict:
        return {"reading": json.loads(text)}


def main() -> None:
    port = int(os.environ.get("PORT", "8088"))
    WorkflowHostServer(graph).run(port=port)


if __name__ == "__main__":
    main()
