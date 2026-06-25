"""Risk Analyser — LangGraph hosted agent for Microsoft Foundry.

Evaluates an energy consumption reading for fraud/theft risk. Delegates the
numeric verdict to the governed ML model (Databricks Model Serving) and grounds
the assessment in energy regulations (Azure AI Search). Exposed via the Foundry
Responses protocol.

Run locally:  python main.py   (serves on http://localhost:8088/responses)
Deploy:       azd ai agent deploy   (or Foundry Toolkit VS Code extension)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the shared package importable both locally and in the hosted container.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent  # noqa: E402
from langchain_azure_ai.agents.hosting import ResponsesHostServer  # noqa: E402

from shared.model import build_chat_model  # noqa: E402
from shared.observability import enable_tracing  # noqa: E402
from shared.tools.model_serving_tool import score_consumption_with_ml_model  # noqa: E402
from shared.tools.regulations_tool import search_energy_regulations  # noqa: E402

enable_tracing("risk-analyzer")

INSTRUCTIONS = """You are a Risk Analyser Agent evaluating energy consumption patterns for potential fraud and theft.

For each reading and customer profile:
1. Call score_consumption_with_ml_model to obtain the governed ML model's verdict (fraud_probability, anomaly_score). This is your authoritative numeric signal.
2. Call search_energy_regulations to find energy regulations relevant to the reading and cross-check the model verdict against them.
3. Assign a fraud risk score from 0 to 100, anchored on the model's fraud_probability and adjusted by regulatory context.

Risk factors to consider:
- high_consumption_threshold_kwh: 1000
- low_consumption_threshold_percent: 50
- suspicious_account_age_days: 30
- low_meter_trust_threshold: 0.5

Always call score_consumption_with_ml_model first, then search_energy_regulations.

Output:
- risk_score: integer (0-100)
- risk_level: [Low, Medium, High]
- model_verdict: the fraud_probability, anomaly_score and model_version returned by the model
- reason: a brief explainable summary citing the model verdict and relevant regulations
"""

graph = create_agent(
    build_chat_model(),
    tools=[score_consumption_with_ml_model, search_energy_regulations],
    system_prompt=INSTRUCTIONS,
)


def main() -> None:
    port = int(os.environ.get("PORT", "8088"))
    ResponsesHostServer(graph).run(port=port)


if __name__ == "__main__":
    main()
