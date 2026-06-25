"""LangChain tool: governed energy-theft verdict from the ML model."""

from __future__ import annotations

from langchain_core.tools import tool

from .model_serving import score_consumption_async


@tool
async def score_consumption_with_ml_model(
    consumption_kwh: float,
    baseline_consumption_kwh: float,
    meter_trust_score: float,
    account_age_days: int,
    past_fraud: bool,
    reading_type: str,
    reading_id: str = "",
    customer_id: str = "",
) -> dict:
    """Get the governed energy-theft verdict for a consumption reading from the
    Databricks Model Serving endpoint (or its mock).

    Always call this first to obtain the model's fraud_probability and
    anomaly_score before assigning a final risk score. The model is the
    authoritative numeric source.

    Args:
        consumption_kwh: The meter reading consumption in kWh for the period.
        baseline_consumption_kwh: The customer's expected baseline consumption in kWh.
        meter_trust_score: Meter trust score between 0 and 1.
        account_age_days: Age of the customer account in days.
        past_fraud: Whether the customer has prior fraud history.
        reading_type: Reading type, e.g. 'Automated' or 'Manual'.
        reading_id: The meter reading identifier.
        customer_id: The customer identifier.
    """
    return await score_consumption_async(
        {
            "consumption_kwh": consumption_kwh,
            "baseline_consumption_kwh": baseline_consumption_kwh,
            "meter_trust_score": meter_trust_score,
            "account_age_days": account_age_days,
            "past_fraud": past_fraud,
            "reading_type": reading_type,
            "reading_id": reading_id,
            "customer_id": customer_id,
        }
    )
