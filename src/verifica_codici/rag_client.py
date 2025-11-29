import os
import aiohttp
from typing import Any, Dict, List, Optional

# Default host/endpoint can be overridden by env vars or a full RAG_ENDPOINT URL.
DEFAULT_QUERY_HOST = os.getenv("QUERY_HOST") or os.getenv("RAG_QUERY_HOST") or "http://host.docker.internal:8090"
DEFAULT_QUERY_ENDPOINT = os.getenv("QUERY_ENDPOINT") or os.getenv("RAG_QUERY_ENDPOINT") or "/query"
RAG_ENDPOINT_URL = os.getenv("RAG_ENDPOINT")  # Backward compatibility: full URL still supported
QUERY_TIMEOUT = int(os.getenv("RAG_QUERY_TIMEOUT", "60"))


def build_query_url() -> str:
    """
    Compose the query URL from host + endpoint, unless a full RAG_ENDPOINT is provided.
    """
    if RAG_ENDPOINT_URL:
        return RAG_ENDPOINT_URL
    host = (DEFAULT_QUERY_HOST or "").rstrip("/")
    endpoint = (DEFAULT_QUERY_ENDPOINT or "/query").lstrip("/")
    return f"{host}/{endpoint}"


async def perform_query(
    query: str,
    collection_id: str,
    limit: int = 5,
    search_mode: str = "standard",
    pipeline_version: str = "v2",
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a query against the IntelligenceBox pipeline and return the JSON response.
    Raises an exception on non-200 responses or network issues.
    """
    url = build_query_url()
    payload: Dict[str, Any] = {
        "query": query,
        "collection_name": collection_id,
        "search_mode": search_mode,
        "pipeline_version": pipeline_version,
        "limit": limit,
    }
    if extra_payload:
        payload.update(extra_payload)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=QUERY_TIMEOUT)) as session:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(f"Query failed ({response.status}): {error_text}")
            return await response.json()


async def query_documents(
    query: str,
    collection_id: str,
    limit: int = 5,
    search_mode: str = "standard",
    pipeline_version: str = "v2",
    extra_payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper that returns the documents array from the query response.
    """
    data = await perform_query(
        query=query,
        collection_id=collection_id,
        limit=limit,
        search_mode=search_mode,
        pipeline_version=pipeline_version,
        extra_payload=extra_payload,
    )
    docs = data.get("documents") or []
    return docs if isinstance(docs, list) else []
