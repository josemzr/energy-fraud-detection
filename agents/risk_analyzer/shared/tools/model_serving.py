"""Model Serving abstraction — the seam between the agent and the energy-theft
ML model served by Databricks Model Serving (or its mock).

Speaks the Databricks Model Serving REST protocol so the same client works
against the real endpoint or a mock — switching is a URL change only
(MODEL_SERVING_ENDPOINT). Degrades gracefully so the agent never hard-fails.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx


def _normalize(prediction: dict[str, Any]) -> dict[str, Any]:
    return {
        "fraud_probability": float(prediction.get("fraud_probability", 0.0)),
        "anomaly_score": float(prediction.get("anomaly_score", 0.0)),
        "decision_hint": prediction.get("decision_hint", "MONITOR"),
        "model_name": prediction.get("model_name", "energy-theft-detector"),
        "model_version": prediction.get("model_version", "unknown"),
        "explanation": prediction.get("explanation", ""),
        "source": "model-serving",
    }


def _unavailable() -> dict[str, Any]:
    return {
        "fraud_probability": 0.0,
        "anomaly_score": 0.0,
        "decision_hint": "MONITOR",
        "model_name": "energy-theft-detector",
        "model_version": "unavailable",
        "explanation": "MODEL_SERVING_ENDPOINT is not set; ML verdict unavailable.",
        "source": "unavailable",
    }


def _error(endpoint: str, exc: Exception) -> dict[str, Any]:
    detail = ""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f" | HTTP {exc.response.status_code}: {exc.response.text[:300]}"
    print(
        f"[model_serving] call to {endpoint} failed: {type(exc).__name__}: {exc}{detail}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "fraud_probability": 0.0,
        "anomaly_score": 0.0,
        "decision_hint": "MONITOR",
        "model_name": "energy-theft-detector",
        "model_version": "error",
        "explanation": f"ML verdict unavailable ({type(exc).__name__}): {exc}{detail}",
        "source": "error",
    }


def _config() -> tuple[str | None, dict[str, str], float]:
    endpoint = os.environ.get("MODEL_SERVING_ENDPOINT")
    token = os.environ.get("MODEL_SERVING_TOKEN")
    timeout = float(os.environ.get("MODEL_SERVING_TIMEOUT", "90"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return endpoint, headers, timeout


async def score_consumption_async(features: dict[str, Any]) -> dict[str, Any]:
    """Async scoring — preferred from the hosted (async) agent runtime."""
    endpoint, headers, timeout = _config()
    if not endpoint:
        return _unavailable()
    payload = {"dataframe_records": [features]}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        predictions = (response.json().get("predictions") or [])
        if not predictions:
            raise ValueError("Model Serving response contained no predictions")
        return _normalize(predictions[0])
    except Exception as exc:  # noqa: BLE001 - demo-safe degradation
        return _error(endpoint, exc)


def score_consumption(features: dict[str, Any]) -> dict[str, Any]:
    """Sync scoring — for smoke tests / non-async callers."""
    endpoint, headers, timeout = _config()
    if not endpoint:
        return _unavailable()
    payload = {"dataframe_records": [features]}
    try:
        response = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        predictions = (response.json().get("predictions") or [])
        if not predictions:
            raise ValueError("Model Serving response contained no predictions")
        return _normalize(predictions[0])
    except Exception as exc:  # noqa: BLE001 - demo-safe degradation
        return _error(endpoint, exc)
