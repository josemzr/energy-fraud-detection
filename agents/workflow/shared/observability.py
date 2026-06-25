"""Observability helper — wires LangGraph/LangChain spans to Application Insights.

On Foundry hosted agents the platform already configures the Azure Monitor
exporter from the project's connected Application Insights, so we only need to
inject the Azure GenAI tracer into the LangChain/LangGraph callback managers.
This produces rich traces (LLM calls, tool calls, per-node spans) instead of
bare HTTP spans. Content recording is enabled so prompts/responses — including a
blocked prompt-injection attempt — are visible in the trace timeline.

Safe to call once at startup; failures degrade gracefully (no tracing, no crash).
"""

from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger(__name__)


def enable_tracing(service_name: str) -> None:
    """Enable Azure AI auto-tracing for this hosted agent.

    Args:
        service_name: Logical name used to tag emitted spans (e.g. ``workflow``).
    """
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    try:
        from langchain_azure_ai.callbacks.tracers import enable_auto_tracing

        enable_auto_tracing(
            enable_content_recording=True,
            agent_id=service_name,
        )
        LOGGER.info("Azure AI auto-tracing enabled for %s", service_name)
    except Exception as exc:  # pragma: no cover - observability must never crash the agent
        LOGGER.warning("Auto-tracing not enabled for %s: %s", service_name, exc)
