"""Read-only API for the Energy Fraud Detection dashboard.

Serves data from the Databricks lakehouse for a read-only portal and for a
voice customer-agent (via MCP through Azure API Management):

  GET /api/customers                              -> customer profiles
  GET /api/investigations                         -> all investigations (newest first)
  GET /api/investigations/{customer_id}           -> one customer's investigations
  GET /api/investigations/{customer_id}/latest    -> that customer's most recent case
  GET /api/readings/latest                        -> latest meter readings

No write operations: the dashboard never launches the workflow. Investigations
are produced by the fraud-detection workflow and persisted to the
`<catalog>.<schema>.analysis_results` Delta table.

Configuration (environment variables):
  DATABRICKS_WORKSPACE_HOSTNAME   e.g. adb-xxxx.azuredatabricks.net
  DATABRICKS_WAREHOUSE_ID         SQL Warehouse id used to run queries
  DATABRICKS_TOKEN                Databricks PAT (or MODEL_SERVING_TOKEN)
  LAKEHOUSE_SCHEMA                catalog.schema holding the tables (default main.fraud)

Run locally (from app/backend):
  uvicorn main:app --reload --port 8000

This is a proof of concept: data-plane auth is a Databricks token. For
production, prefer a managed identity / OAuth and least-privilege access.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load a local .env if present (repo root, two levels up from app/backend).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

DBX_HOST = os.environ.get("DATABRICKS_WORKSPACE_HOSTNAME", "")
DBX_WAREHOUSE = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
# catalog.schema that holds the customers / transactions / analysis_results tables.
LAKEHOUSE_SCHEMA = os.environ.get("LAKEHOUSE_SCHEMA", "main.fraud")
RESULTS_TABLE = os.environ.get("RESULTS_TABLE", f"{LAKEHOUSE_SCHEMA}.analysis_results")
CUSTOMERS_TABLE = os.environ.get("CUSTOMERS_TABLE", f"{LAKEHOUSE_SCHEMA}.customers")
TRANSACTIONS_TABLE = os.environ.get("TRANSACTIONS_TABLE", f"{LAKEHOUSE_SCHEMA}.transactions")


def _dbx_token() -> str:
    token = (
        os.environ.get("DATABRICKS_TOKEN")
        or os.environ.get("MODEL_SERVING_TOKEN")
        or os.environ.get("GENIE_MCP_TOKEN")
    )
    if not token:
        raise HTTPException(500, "No Databricks token configured (DATABRICKS_TOKEN / MODEL_SERVING_TOKEN).")
    return token


async def _dbsql(statement: str, parameters: list[dict] | None = None) -> list[dict]:
    """Run a SQL statement via the Databricks Statement Execution API; return list of row dicts."""
    payload: dict[str, Any] = {
        "warehouse_id": DBX_WAREHOUSE,
        "statement": statement,
        "wait_timeout": "30s",
    }
    if parameters:
        payload["parameters"] = parameters
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(
            f"https://{DBX_HOST}/api/2.0/sql/statements",
            headers={"Authorization": f"Bearer {_dbx_token()}"},
            json=payload,
        )
    resp.raise_for_status()
    data = resp.json()
    state = data.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise HTTPException(502, f"Databricks query failed: {data.get('status', {}).get('error')}")
    cols = [c["name"] for c in data.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = data.get("result", {}).get("data_array", []) or []
    return [dict(zip(cols, r)) for r in rows]


app = FastAPI(
    title="Energy Fraud Detection API",
    description=(
        "Read-only REST API for the Energy Fraud Detection portal. Exposes customer "
        "profiles, meter readings and the fraud-detection investigations stored in the "
        "Databricks lakehouse. Designed to be imported into Azure API Management and "
        "exposed as an MCP server (e.g. for a voice customer-agent)."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC: open CORS for the local Angular dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/api/customers",
    operation_id="list_customers",
    summary="List customer profiles",
    description=(
        "Return all energy customers with their fraud-risk attributes (region, account age, "
        "meter trust score, prior-fraud flag, property type and baseline consumption). "
        "Highest-risk customers (prior fraud, low meter trust) first."
    ),
    tags=["customers"],
)
async def customers() -> list[dict]:
    return await _dbsql(
        f"SELECT customer_id, name, region, account_age_days, meter_trust_score, "
        f"past_fraud, property_type, baseline_consumption_kwh FROM {CUSTOMERS_TABLE} "
        f"ORDER BY past_fraud DESC, meter_trust_score ASC"
    )


@app.get(
    "/api/investigations",
    operation_id="list_investigations",
    summary="List all fraud investigations",
    description=(
        "Return the fraud-detection investigations across all customers (newest first): "
        "customer, case status (CLEAN, or BLOCKED when Prompt Shields stopped a "
        "prompt-injection attempt), risk score, risk level, fraud probability and a summary. "
        "Limit defaults to 50 (max 200)."
    ),
    tags=["investigations"],
)
async def investigations(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    return await _dbsql(
        "SELECT a.analysis_id, a.created_at, a.customer_id, c.name AS customer_name, "
        "c.region, a.security_status, a.risk_score, a.risk_level, a.fraud_probability, "
        "a.summary "
        f"FROM {RESULTS_TABLE} a "
        f"LEFT JOIN {CUSTOMERS_TABLE} c ON a.customer_id = c.customer_id "
        f"ORDER BY a.created_at DESC LIMIT {limit}"
    )


async def _investigations_for(customer_id: str, limit: int) -> list[dict]:
    """Fetch a customer's fraud investigations (joined with their profile name)."""
    limit = max(1, min(limit, 50))
    return await _dbsql(
        "SELECT a.analysis_id, a.created_at, a.customer_id, c.name AS customer_name, "
        "c.region, a.security_status, a.risk_score, a.risk_level, a.fraud_probability, "
        "a.summary, a.compliance_report, a.fraud_alert "
        f"FROM {RESULTS_TABLE} a "
        f"LEFT JOIN {CUSTOMERS_TABLE} c ON a.customer_id = c.customer_id "
        "WHERE a.customer_id = :customer_id "
        f"ORDER BY a.created_at DESC LIMIT {limit}",
        parameters=[{"name": "customer_id", "value": customer_id, "type": "STRING"}],
    )


@app.get(
    "/api/investigations/{customer_id}",
    operation_id="get_customer_investigations",
    summary="Get a customer's fraud investigations",
    description=(
        "Return the fraud-detection investigations recorded for a specific customer "
        "(newest first), including case status, risk level, risk score, fraud probability, "
        "the compliance outcome and the fraud-alert decision. Use this to tell a customer "
        "who received a fraud-investigation notice the details of their case."
    ),
    tags=["investigations"],
)
async def customer_investigations(customer_id: str, limit: int = 10) -> list[dict]:
    return await _investigations_for(customer_id, limit)


@app.get(
    "/api/investigations/{customer_id}/latest",
    operation_id="get_latest_customer_investigation",
    summary="Get a customer's most recent investigation",
    description=(
        "Return the single most recent fraud-detection investigation for a customer, or "
        "404 if none exists. Convenient for a voice agent answering "
        "'what is the status of my case?'."
    ),
    tags=["investigations"],
)
async def latest_customer_investigation(customer_id: str) -> dict:
    rows = await _investigations_for(customer_id, 1)
    if not rows:
        raise HTTPException(404, f"No investigation found for customer {customer_id}.")
    return rows[0]


@app.get(
    "/api/investigation/{analysis_id}",
    operation_id="get_investigation",
    summary="Get one investigation in full detail",
    description=(
        "Return a single fraud-detection investigation by its analysis_id, with the full "
        "detail an analyst needs: case status, risk score/level, fraud probability, the "
        "customer profile (region, account age, meter trust, prior fraud, property type, "
        "baseline consumption), the analysed reading, and the risk-analysis, compliance and "
        "fraud-alert narratives. Returns 404 if the analysis_id is unknown."
    ),
    tags=["investigations"],
)
async def investigation(analysis_id: str) -> dict:
    rows = await _dbsql(
        "SELECT a.analysis_id, a.created_at, a.customer_id, c.name AS customer_name, "
        "c.region, c.account_age_days, c.meter_trust_score, c.past_fraud, c.property_type, "
        "c.baseline_consumption_kwh, a.security_status, a.risk_score, a.risk_level, "
        "a.fraud_probability, a.summary, a.risk_analysis, a.compliance_report, "
        "a.fraud_alert, a.reading_json "
        f"FROM {RESULTS_TABLE} a "
        f"LEFT JOIN {CUSTOMERS_TABLE} c ON a.customer_id = c.customer_id "
        "WHERE a.analysis_id = :analysis_id LIMIT 1",
        parameters=[{"name": "analysis_id", "value": analysis_id, "type": "STRING"}],
    )
    if not rows:
        raise HTTPException(404, f"No investigation found with id {analysis_id}.")
    return rows[0]


@app.get(
    "/api/readings/latest",
    operation_id="get_latest_readings",
    summary="Get the latest meter readings",
    description=(
        "Return the most recent smart-meter readings (newest first) joined with the "
        "customer name, baseline consumption and region. Limit defaults to 50 (max 200)."
    ),
    tags=["readings"],
)
async def latest_readings(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    return await _dbsql(
        "SELECT t.reading_id, t.customer_id, c.name AS customer_name, c.region, "
        "t.consumption_kwh, c.baseline_consumption_kwh, t.meter_id, t.reading_type, "
        "t.timestamp "
        f"FROM {TRANSACTIONS_TABLE} t "
        f"LEFT JOIN {CUSTOMERS_TABLE} c ON t.customer_id = c.customer_id "
        f"ORDER BY t.timestamp DESC LIMIT {limit}"
    )


@app.get(
    "/api/health",
    operation_id="health_check",
    summary="Health check",
    description="Liveness probe for the API.",
    tags=["system"],
)
async def health() -> dict:
    return {"status": "ok"}


# Serve the built Angular dashboard (same-origin) when present (container build).
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
