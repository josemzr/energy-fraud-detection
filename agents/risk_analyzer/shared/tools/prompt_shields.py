"""Prompt Shields guardrail — detects direct and indirect prompt-injection /
jailbreak attacks using Azure AI Content Safety (shieldPrompt).

This is the antidote demonstrated in the security twist: malicious instructions
embedded in meter-reading data (indirect prompt injection) are detected BEFORE
the agent acts on them.

Auth: Entra (DefaultAzureCredential) by default; a key (CONTENT_SAFETY_KEY)
overrides if present. Endpoint defaults to the project's AI Services account.

Environment:
  CONTENT_SAFETY_ENDPOINT   e.g. https://frauddetozah.cognitiveservices.azure.com
  CONTENT_SAFETY_KEY        optional; if set, used instead of Entra auth
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

_SCOPE = "https://cognitiveservices.azure.com/.default"
_DEFAULT_ENDPOINT = "https://frauddetozah.cognitiveservices.azure.com"
_token_provider = None


def _endpoint() -> str:
    return os.environ.get("CONTENT_SAFETY_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")


def _headers() -> dict[str, str]:
    key = os.environ.get("CONTENT_SAFETY_KEY")
    if key:
        return {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json"}
    global _token_provider
    if _token_provider is None:
        _token_provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
    return {"Authorization": f"Bearer {_token_provider()}", "Content-Type": "application/json"}


def extract_reading_text(reading: dict) -> list[str]:
    """Collect the free-text fields of a reading that could carry injected text."""
    return [str(v) for v in reading.values() if isinstance(v, str) and v.strip()]


async def detect_prompt_injection(user_prompt: str, documents: list[str]) -> dict[str, Any]:
    """Run Prompt Shields on a user prompt and supporting documents.

    Returns: {attack_detected, user_prompt_attack, document_attacks, source}.
    Degrades safely (attack_detected=False with error) so it never hard-fails the flow.
    """
    url = f"{_endpoint()}/contentsafety/text:shieldPrompt?api-version=2024-09-01"
    payload = {"userPrompt": user_prompt or "", "documents": [d for d in documents if d]}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        body = response.json()
        user_attack = bool(body.get("userPromptAnalysis", {}).get("attackDetected"))
        doc_attacks = [bool(d.get("attackDetected")) for d in body.get("documentsAnalysis", [])]
        return {
            "attack_detected": user_attack or any(doc_attacks),
            "user_prompt_attack": user_attack,
            "document_attacks": doc_attacks,
            "source": "prompt-shields",
        }
    except Exception as exc:  # noqa: BLE001 - demo-safe degradation
        return {
            "attack_detected": False,
            "user_prompt_attack": False,
            "document_attacks": [],
            "error": f"{type(exc).__name__}: {exc}",
            "source": "error",
        }
