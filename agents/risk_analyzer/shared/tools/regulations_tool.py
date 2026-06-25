"""LangChain tool: client-side energy-regulations search over Azure AI Search."""

from __future__ import annotations

import os

from langchain_core.tools import tool

INDEX_NAME = os.environ.get("REGULATIONS_INDEX_NAME", "regulations-policies")


@tool
def search_energy_regulations(query: str, top: int = 3) -> list[dict]:
    """Search energy regulations and compliance policies relevant to a reading.

    Returns regulation snippets from the governed regulations index. Use this to
    ground the risk assessment in Spanish/EU electricity regulations (e.g. Ley 24/2013
    del Sector Eléctrico, RD 1955/2000) on metering fraud and supply.

    Args:
        query: Natural-language query, e.g. 'meter bypass low consumption'.
        top: Number of regulation snippets to return.
    """
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT") or os.environ.get("SEARCH_SERVICE_ENDPOINT")
    key = os.environ.get("AZURE_SEARCH_API_KEY") or os.environ.get("SEARCH_ADMIN_KEY")
    if not endpoint or not key:
        return [{"error": "Azure AI Search is not configured (endpoint/key missing)."}]

    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        client = SearchClient(
            endpoint=endpoint,
            index_name=INDEX_NAME,
            credential=AzureKeyCredential(key),
        )
        results = client.search(search_text=query, top=top)
        snippets = [
            {k: v for k, v in doc.items() if not k.startswith("@search") and v is not None}
            for doc in results
        ]
        return snippets or [{"info": "No matching regulations found."}]
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"Regulation search failed: {type(exc).__name__}: {exc}"}]
