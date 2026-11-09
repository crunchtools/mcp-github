"""Shared test fixtures for mcp-github tests."""

import os
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_client_singleton() -> Generator[None, None, None]:
    """Reset the global client and config singletons between tests."""
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None
    yield
    client_mod._client = None
    config_mod._config = None


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    text: str = "",
    content_type: str = "application/json",
    headers: dict | None = None,
) -> httpx.Response:
    """Build a mock httpx.Response."""
    resp_headers = {"content-type": content_type}
    if headers:
        resp_headers.update(headers)
    return httpx.Response(
        status_code=status_code,
        headers=resp_headers,
        json=json_data if json_data is not None else None,
        text=text if json_data is None else None,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


def _answer(template: httpx.Response, request: httpx.Request) -> httpx.Response:
    """A fresh response with a template's status, type and body, for one request.

    Fresh because a streamed body can be read once, and because the error
    messages under test name `response.request.url` -- the URL the client
    actually built, not the placeholder a template carries. Content-length is
    dropped so httpx recomputes it, unless a test set one deliberately.
    """
    keep = template.headers.get("content-length") if "content-length" in template.headers else None
    headers = {k: v for k, v in template.headers.items() if k.lower() != "content-length"}
    response = httpx.Response(
        template.status_code, headers=headers, content=template.content, request=request
    )
    if keep is not None:
        response.headers["content-length"] = keep
    return response


def _mock_http(**send: Any) -> AsyncMock:
    """A stand-in for the client, whose `build_request` builds a real request.

    The client streams now: `build_request` then `send(..., stream=True)`. A
    real `httpx.Client` builds the request, so assertions on the method, url,
    params, json and headers a caller passed still mean what they did, while
    `send` is what each test scripts.

    What this cannot see is the client's own behaviour -- the User-Agent it
    adds and the bounded read it performs. Those are tested through
    `_patch_transport`, which uses a real client (constitution v1.36.0,
    Layer 3).
    """
    builder = httpx.Client(base_url="https://api.github.com")
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.build_request = MagicMock(side_effect=builder.build_request)
    mock_http.send = AsyncMock(**send)
    return mock_http


def _patch_client(mock_response: httpx.Response):
    """Patch the AsyncClient so every request is answered with one response."""
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None
    os.environ.setdefault("GITHUB_TOKEN", "ghp_test_mock_token")

    return patch.object(httpx, "AsyncClient", return_value=_mock_http(return_value=mock_response))


def _patch_client_sequence(*mock_responses: httpx.Response):
    """Patch the AsyncClient to answer with a sequence of responses."""
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None
    os.environ.setdefault("GITHUB_TOKEN", "ghp_test_mock_token")

    return patch.object(
        httpx, "AsyncClient", return_value=_mock_http(side_effect=list(mock_responses))
    )


def _patch_transport(handler: Callable[[httpx.Request], httpx.Response]):
    """Patch AsyncClient so real clients send through a mock transport.

    Unlike _patch_client, the httpx client itself is real: the handler sees
    each request as it would go on the wire, default headers included. Use it
    where the headers of a request, or streaming, are what is under test.
    """
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None

    os.environ.setdefault("GITHUB_TOKEN", "ghp_test_mock_token")

    real_client = httpx.AsyncClient

    def build(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return patch.object(httpx, "AsyncClient", side_effect=build)
