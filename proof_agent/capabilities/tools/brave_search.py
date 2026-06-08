from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import HttpUrl, TypeAdapter

from proof_agent.contracts import ToolSource, ToolSourceLifecycleState, UntrustedWebResult
from proof_agent.errors import ProofAgentError

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESULTS = 3
MAX_RESULTS_LIMIT = 10
_HTTP_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


@dataclass(frozen=True)
class BraveSearchRequest:
    query: str
    count: int
    api_key: str
    timeout_seconds: float


BraveSearchTransport = Callable[[BraveSearchRequest], Mapping[str, Any]]
ToolHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def create_brave_untrusted_web_search_handler(
    source: ToolSource,
    *,
    env: Mapping[str, str],
    transport: BraveSearchTransport | None = None,
) -> ToolHandler:
    """Create a ToolGateway handler for a Dashboard-managed Brave Search Tool Source."""

    if source.provider != "brave_search":
        raise _tool_source_error(
            f"Tool Source {source.source_id} is not a Brave Search source.",
            "Bind an active Tool Source with provider=brave_search.",
        )
    if "untrusted_web_search" not in source.tool_contract_ids:
        raise _tool_source_error(
            f"Tool Source {source.source_id} does not expose untrusted_web_search.",
            "Update the Tool Source descriptor or Agent Tool Binding.",
        )

    selected_transport = transport or _default_brave_search_transport

    def handler(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        if source.lifecycle_state is ToolSourceLifecycleState.ARCHIVED:
            raise _tool_source_error(
                f"Tool Source {source.source_id} is archived.",
                "Restore the Tool Source or select another active Tool Source.",
            )
        credential_env_ref = (source.credential_env_ref or "").strip()
        if not credential_env_ref:
            raise _tool_source_error(
                f"Tool Source {source.source_id} is missing credential_env_ref.",
                "Configure an environment variable reference for the Tool Source.",
            )
        api_key = env.get(credential_env_ref, "").strip()
        if not api_key:
            raise _tool_source_error(
                f"Tool Source credential env var is missing: {credential_env_ref}.",
                "Set the referenced environment variable before validating or running the tool.",
            )
        query = str(parameters.get("query", "")).strip()
        count = _requested_count(parameters, source)
        response = selected_transport(
            BraveSearchRequest(
                query=query,
                count=count,
                api_key=api_key,
                timeout_seconds=_timeout_seconds(source),
            )
        )
        results = _normalize_brave_results(response, limit=count)
        return {
            "provider": "brave_search",
            "tool_source_id": source.source_id,
            "tool_source_config_revision": source.config_revision,
            "result_count": len(results),
            "results": [result.model_dump(mode="json") for result in results],
        }

    return handler


def _default_brave_search_transport(request: BraveSearchRequest) -> Mapping[str, Any]:
    query = urlencode({"q": request.query, "count": request.count})
    http_request = Request(
        f"{BRAVE_WEB_SEARCH_URL}?{query}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": request.api_key,
        },
        method="GET",
    )
    try:
        with urlopen(http_request, timeout=request.timeout_seconds) as response:
            body = response.read()
    except HTTPError as exc:
        raise _tool_source_error(
            f"Brave Search request failed with HTTP {exc.code}.",
            "Validate the Tool Source credential and provider availability.",
        ) from exc
    except URLError as exc:
        raise _tool_source_error(
            "Brave Search request failed before receiving a response.",
            "Check network access and provider availability.",
        ) from exc
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise _tool_source_error(
            "Brave Search response was not a JSON object.",
            "Validate provider response shape before using the Tool Source.",
        )
    return cast(Mapping[str, Any], payload)


def _normalize_brave_results(
    response: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[UntrustedWebResult, ...]:
    raw_results = response.get("web", {})
    if not isinstance(raw_results, Mapping):
        return ()
    items = raw_results.get("results", [])
    if not isinstance(items, list | tuple):
        return ()
    normalized: list[UntrustedWebResult] = []
    for item in items:
        if len(normalized) >= limit:
            break
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("description", "")).strip()
        if not title or not url or not snippet:
            continue
        normalized.append(
            UntrustedWebResult(
                title=title,
                url=_HTTP_URL_ADAPTER.validate_python(url),
                snippet=snippet,
                provider="brave_search",
                rank=len(normalized) + 1,
                domain=urlparse(url).netloc,
                published_at=_optional_string(item.get("age")),
            )
        )
    return tuple(normalized)


def _requested_count(parameters: Mapping[str, Any], source: ToolSource) -> int:
    raw = parameters.get("max_results", source.params.get("default_max_results"))
    if raw is None:
        raw = DEFAULT_MAX_RESULTS
    try:
        count = int(raw)
    except (TypeError, ValueError):
        count = DEFAULT_MAX_RESULTS
    return max(1, min(count, MAX_RESULTS_LIMIT))


def _timeout_seconds(source: ToolSource) -> float:
    raw = source.params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return max(1.0, timeout)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tool_source_error(message: str, remediation: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_TOOL_SOURCE_002",
        message,
        remediation,
    )
