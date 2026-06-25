"""Persist workflow analysis results to a Databricks Delta table.

Writes one row per workflow run (risk verdict, compliance, fraud alert and the
Prompt Shields security status) to `RESULTS_TABLE` via the Databricks SQL
Statement Execution API. Parameterized statements are used so free-text agent
output cannot break or inject into the SQL.

Environment:
  DATABRICKS_WORKSPACE_HOSTNAME   e.g. adb-7405619936090888.8.azuredatabricks.net
  DATABRICKS_WAREHOUSE_ID         SQL Warehouse id used to run the INSERT
  DATABRICKS_TOKEN | MODEL_SERVING_TOKEN | GENIE_MCP_TOKEN   bearer token
  RESULTS_TABLE                   fully-qualified table (default adbdemo1.fraud.analysis_results)

Persistence is best-effort: any failure is logged and swallowed so it never
breaks the workflow.
"""

from __future__ import annotations

import logging
import os

import httpx

LOGGER = logging.getLogger(__name__)

_DEFAULT_TABLE = "adbdemo1.fraud.analysis_results"


def _hostname() -> str:
    return os.environ["DATABRICKS_WORKSPACE_HOSTNAME"].rstrip("/")


def _token() -> str:
    token = (
        os.environ.get("DATABRICKS_TOKEN")
        or os.environ.get("MODEL_SERVING_TOKEN")
        or os.environ.get("GENIE_MCP_TOKEN")
    )
    if not token:
        raise RuntimeError(
            "Set DATABRICKS_TOKEN (or MODEL_SERVING_TOKEN / GENIE_MCP_TOKEN) to persist results."
        )
    return token


def _results_table() -> str:
    return os.environ.get("RESULTS_TABLE", _DEFAULT_TABLE)


async def persist_analysis_result(record: dict) -> bool:
    """Insert one analysis record. Returns True on success, False on any failure."""
    table = _results_table()
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        LOGGER.warning("DATABRICKS_WAREHOUSE_ID not set; skipping result persistence.")
        return False

    statement = (
        f"INSERT INTO {table} "
        "(analysis_id, created_at, customer_id, security_status, risk_score, "
        " risk_level, fraud_probability, summary, risk_analysis, compliance_report, "
        " fraud_alert, reading_json) "
        "VALUES (:analysis_id, current_timestamp(), :customer_id, :security_status, "
        " :risk_score, :risk_level, :fraud_probability, :summary, :risk_analysis, "
        " :compliance_report, :fraud_alert, :reading_json)"
    )

    def _p(name: str, value, type_: str) -> dict:
        if value is None:
            return {"name": name, "value": None, "type": type_}
        return {"name": name, "value": str(value), "type": type_}

    parameters = [
        _p("analysis_id", record.get("analysis_id"), "STRING"),
        _p("customer_id", record.get("customer_id"), "STRING"),
        _p("security_status", record.get("security_status"), "STRING"),
        _p("risk_score", record.get("risk_score"), "INT"),
        _p("risk_level", record.get("risk_level"), "STRING"),
        _p("fraud_probability", record.get("fraud_probability"), "DOUBLE"),
        _p("summary", record.get("summary"), "STRING"),
        _p("risk_analysis", record.get("risk_analysis"), "STRING"),
        _p("compliance_report", record.get("compliance_report"), "STRING"),
        _p("fraud_alert", record.get("fraud_alert"), "STRING"),
        _p("reading_json", record.get("reading_json"), "STRING"),
    ]

    payload = {
        "warehouse_id": warehouse_id,
        "statement": statement,
        "parameters": parameters,
        "wait_timeout": "30s",
    }

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"https://{_hostname()}/api/2.0/sql/statements",
                headers={"Authorization": f"Bearer {_token()}"},
                json=payload,
            )
        resp.raise_for_status()
        state = resp.json().get("status", {}).get("state")
        if state == "SUCCEEDED":
            LOGGER.info("Persisted analysis result %s to %s", record.get("analysis_id"), table)
            return True
        LOGGER.warning("Result persistence returned state=%s: %s", state, resp.text[:300])
        return False
    except Exception as exc:  # pragma: no cover - persistence must never break the workflow
        LOGGER.warning("Failed to persist analysis result: %s", exc)
        return False
