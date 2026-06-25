"""Fraud detection workflow as a LangGraph graph (deployable as a Foundry hosted agent).

Mirrors the multi-agent flow:

    customer_data -> risk_analyzer -> ┬─> compliance_report
                                      └─> fraud_alert

The Risk Analyzer node delegates the numeric verdict to the governed Databricks
ML model and grounds it in energy regulations. A Genie-powered forensics node is
available for natural-language investigation of the Lakehouse.

Models are built lazily (per node) so importing this module does not require a
live Foundry connection.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from shared.model import build_chat_model
from shared.tools.model_serving_tool import score_consumption_with_ml_model
from shared.tools.regulations_tool import search_energy_regulations
from shared.tools.prompt_shields import detect_prompt_injection, extract_reading_text
from shared.tools.results_store import persist_analysis_result

RISK_INSTRUCTIONS = """You are a Risk Analyser for energy fraud. For the given reading and customer profile:
1. Call score_consumption_with_ml_model to obtain the governed ML model verdict (fraud_probability, anomaly_score).
2. Call search_energy_regulations to ground the assessment in Spanish/EU electricity regulations (Ley 24/2013 del Sector Eléctrico, RD 1955/2000) on metering fraud.
3. Return: risk_score (0-100), risk_level (Low/Medium/High), model_verdict, and a concise reason."""

COMPLIANCE_INSTRUCTIONS = """You are a Compliance Report Agent. Given a risk assessment, produce a formal
energy-compliance audit: compliance_rating (COMPLIANT/CONDITIONAL_COMPLIANCE/NON_COMPLIANT), required
actions (field inspection, meter replacement, billing hold, theft case), and whether regulatory filing
is required."""

FRAUD_ALERT_INSTRUCTIONS = """You are a Fraud Alert Agent. Given a risk assessment, decide whether to raise
a fraud alert and with what severity (LOW/MEDIUM/HIGH/CRITICAL) and decision action
(ALLOW/BLOCK/MONITOR/INVESTIGATE). Provide clear reasoning."""


class FraudState(TypedDict, total=False):
    # 'messages' is required by InvocationsHostServer's schema validation and is
    # where the final consolidated result is returned to the caller.
    messages: Annotated[list, add_messages]
    reading: dict
    security: dict
    risk_analysis: str
    compliance_report: str
    fraud_alert: str


def _last_text(result: dict) -> str:
    messages = result.get("messages") or []
    return messages[-1].content if messages else ""


async def guardrail_node(state: FraudState) -> dict:
    """Prompt Shields guardrail. Scans the reading's free-text fields for direct
    or indirect prompt-injection before any agent acts on the data."""
    reading = state["reading"]
    documents = extract_reading_text(reading)
    result = await detect_prompt_injection(
        "Assess this meter reading for energy fraud.", documents
    )
    return {"security": result}


async def blocked_node(state: FraudState) -> dict:
    """Antidote: a prompt-injection attempt was detected. Do NOT let the agent
    act on the injected instructions; hold the case for human review (HITL)."""
    sec = state.get("security", {})
    detail = (
        "Prompt injection / jailbreak attempt detected in the reading data by "
        "Azure AI Content Safety Prompt Shields. The agent did NOT act on the "
        "embedded instructions."
    )
    return {
        "compliance_report": (
            f"SECURITY BLOCK: {detail} Case held pending human review. "
            f"Shield result: {json.dumps(sec)}"
        ),
        "fraud_alert": (
            "BLOCKED — severity HIGH, decision INVESTIGATE. Suspected adversarial "
            "manipulation of meter-reading data; escalated to a human analyst."
        ),
    }


def route_after_guardrail(state: FraudState) -> str:
    return "blocked" if state.get("security", {}).get("attack_detected") else "risk_analyzer"


async def summarize_node(state: FraudState) -> dict:
    """Consolidate the workflow result into a single message for the caller."""
    if state.get("security", {}).get("attack_detected"):
        summary = (
            "🛡️ SECURITY BLOCK — Prompt Shields detected a prompt-injection attempt in the "
            "reading data. The agents did NOT act on the injected instructions.\n\n"
            f"{state.get('compliance_report', '')}\n\n{state.get('fraud_alert', '')}"
        )
    else:
        summary = (
            f"RISK ANALYSIS:\n{state.get('risk_analysis', '')}\n\n"
            f"COMPLIANCE REPORT:\n{state.get('compliance_report', '')}\n\n"
            f"FRAUD ALERT:\n{state.get('fraud_alert', '')}"
        )
    return {"messages": [AIMessage(content=summary)]}


async def risk_analyzer_node(state: FraudState) -> dict:
    agent = create_agent(
        build_chat_model(),
        tools=[score_consumption_with_ml_model, search_energy_regulations],
        system_prompt=RISK_INSTRUCTIONS,
    )
    prompt = f"Assess this meter reading and customer profile for energy fraud:\n{json.dumps(state['reading'])}"
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return {"risk_analysis": _last_text(result)}


async def compliance_report_node(state: FraudState) -> dict:
    agent = create_agent(build_chat_model(), tools=[], system_prompt=COMPLIANCE_INSTRUCTIONS)
    prompt = f"Generate the compliance audit for this risk assessment:\n{state.get('risk_analysis', '')}"
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return {"compliance_report": _last_text(result)}


async def fraud_alert_node(state: FraudState) -> dict:
    agent = create_agent(build_chat_model(), tools=[], system_prompt=FRAUD_ALERT_INSTRUCTIONS)
    prompt = f"Decide on a fraud alert for this risk assessment:\n{state.get('risk_analysis', '')}"
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return {"fraud_alert": _last_text(result)}


def _parse_risk(risk_analysis: str) -> dict:
    """Best-effort extraction of structured fields from the risk analysis text."""
    out: dict = {"risk_score": None, "risk_level": None, "fraud_probability": None}
    if not risk_analysis:
        return out
    m = re.search(r"risk[_\s]*score[^0-9]*(\d{1,3})", risk_analysis, re.IGNORECASE)
    if m:
        out["risk_score"] = int(m.group(1))
    m = re.search(r"risk[_\s]*level[^A-Za-z]*(Low|Medium|High)", risk_analysis, re.IGNORECASE)
    if m:
        out["risk_level"] = m.group(1).capitalize()
    m = re.search(r"fraud[_\s]*probability[^0-9]*(0?\.\d+|\d(?:\.\d+)?)", risk_analysis, re.IGNORECASE)
    if m:
        out["fraud_probability"] = float(m.group(1))
    return out


async def persist_node(state: FraudState) -> dict:
    """Persist the workflow result to the Delta table for later querying."""
    reading = state.get("reading", {})
    blocked = bool(state.get("security", {}).get("attack_detected"))
    parsed = _parse_risk(state.get("risk_analysis", ""))
    record = {
        "analysis_id": str(uuid.uuid4()),
        "customer_id": reading.get("customer_id"),
        "security_status": "BLOCKED" if blocked else "CLEAN",
        "risk_score": parsed["risk_score"],
        "risk_level": parsed["risk_level"],
        "fraud_probability": parsed["fraud_probability"],
        "summary": _last_text(state),
        "risk_analysis": state.get("risk_analysis"),
        "compliance_report": state.get("compliance_report"),
        "fraud_alert": state.get("fraud_alert"),
        "reading_json": json.dumps(reading),
    }
    await persist_analysis_result(record)
    return {}


def build_graph():
    """Build and compile the fraud detection workflow graph."""
    workflow = StateGraph(FraudState)
    workflow.add_node("guardrail", guardrail_node)
    workflow.add_node("blocked", blocked_node)
    workflow.add_node("risk_analyzer", risk_analyzer_node)
    workflow.add_node("compliance_report", compliance_report_node)
    workflow.add_node("fraud_alert", fraud_alert_node)
    workflow.add_node("summarize", summarize_node)
    workflow.add_node("persist", persist_node)

    # Security guardrail first: Prompt Shields scans the reading for injection.
    workflow.add_edge(START, "guardrail")
    workflow.add_conditional_edges(
        "guardrail", route_after_guardrail, {"blocked": "blocked", "risk_analyzer": "risk_analyzer"}
    )
    workflow.add_edge("blocked", "summarize")
    # Normal path: fan-out compliance + fraud alert from the risk assessment.
    workflow.add_edge("risk_analyzer", "compliance_report")
    workflow.add_edge("risk_analyzer", "fraud_alert")
    workflow.add_edge("compliance_report", "summarize")
    workflow.add_edge("fraud_alert", "summarize")
    # Persist the consolidated result, then finish.
    workflow.add_edge("summarize", "persist")
    workflow.add_edge("persist", END)

    return workflow.compile()


graph = build_graph()
