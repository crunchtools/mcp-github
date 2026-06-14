"""Shared test fixtures for mcp-github tests."""

import os
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

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


def _patch_client(mock_response: httpx.Response):
    """Patch the httpx AsyncClient to return a mock response.

    Sets GITHUB_TOKEN so config initializes, then mocks the HTTP layer.
    """
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None

    os.environ.setdefault("GITHUB_TOKEN", "ghp_test_mock_token")

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.request = AsyncMock(return_value=mock_response)

    return patch.object(
        httpx, "AsyncClient", return_value=mock_http,
    )


def _patch_client_sequence(*mock_responses: httpx.Response):
    """Patch the AsyncClient to return a sequence of responses."""
    import mcp_github_crunchtools.client as client_mod
    import mcp_github_crunchtools.config as config_mod

    client_mod._client = None
    config_mod._config = None

    os.environ.setdefault("GITHUB_TOKEN", "ghp_test_mock_token")

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.request = AsyncMock(side_effect=list(mock_responses))

    return patch.object(
        httpx, "AsyncClient", return_value=mock_http,
    )
