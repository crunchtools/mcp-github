"""GitHub API client with security hardening.

This module provides a secure async HTTP client for the GitHub REST API.
All requests go through this client to ensure consistent security practices.
"""

import logging
import re
from typing import Any

import httpx

from .config import get_config
from .errors import (
    GitHubApiError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024
REQUEST_TIMEOUT = 30.0
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_ACCEPT = "application/vnd.github+json"

_LINK_ENTRY = re.compile(r'<(?P<url>[^>]+)>;\s*rel="(?P<rel>[^"]+)"')
_PAGE_PARAM = re.compile(r"[?&]page=(\d+)")


class GitHubClient:
    """Async HTTP client for the GitHub REST API.

    Security features:
    - Configurable base URL with HTTPS enforcement (supports GHES)
    - Token passed via Authorization: Bearer header (not URL)
    - TLS certificate validation (httpx default)
    - Request timeout enforcement
    - Response size limits
    - Pagination support via the GitHub Link header
    """

    def __init__(self) -> None:
        """Initialize the GitHub client."""
        self._config = get_config()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.api_base_url,
                headers={
                    "Authorization": f"Bearer {self._config.token}",
                    "Accept": DEFAULT_ACCEPT,
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                verify=self._config.ssl_verify,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> dict[str, Any]:
        """Make an API request with error handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (e.g., /repos/owner/repo/issues)
            params: Query parameters
            json_data: JSON body data
            accept: Optional override for the Accept header (e.g., for diffs)

        Returns:
            API response data with pagination info if applicable. Non-JSON
            responses (such as raw diffs) are returned as {"content": text}.

        Raises:
            GitHubApiError: On API errors
            RateLimitError: On rate limiting
            PermissionDeniedError: On authorization failures
            NotFoundError: When the resource does not exist
        """
        client = await self._get_client()

        logger.debug("API request: %s %s", method, path)

        headers = {"Accept": accept} if accept else None

        try:
            response = await client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
                headers=headers,
            )
        except httpx.TimeoutException as e:
            raise GitHubApiError(0, f"Request timeout: {e}") from e
        except httpx.RequestError as e:
            raise GitHubApiError(0, f"Request failed: {e}") from e

        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_RESPONSE_SIZE:
            raise GitHubApiError(0, "Response too large")

        if not response.is_success:
            self._handle_error_response(response)

        if response.status_code == 204:
            return {"status": "deleted"}

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return {"content": response.text}

        try:
            parsed = response.json()
        except ValueError as e:
            raise GitHubApiError(
                response.status_code, f"Invalid JSON response: {e}"
            ) from e

        if isinstance(parsed, list):
            return self._wrap_list_response(parsed, response)

        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    def _wrap_list_response(
        self, items: list[Any], response: httpx.Response
    ) -> dict[str, Any]:
        """Wrap a list response with pagination parsed from the Link header.

        GitHub signals pagination through the RFC 5988 Link header rather than
        x-total-* headers. Each rel (next, prev, first, last) maps to a URL; we
        surface both the URLs and their page numbers.
        """
        wrapped: dict[str, Any] = {"items": items}

        pagination: dict[str, Any] = {}
        link_header = response.headers.get("link")
        if link_header:
            for match in _LINK_ENTRY.finditer(link_header):
                rel = match.group("rel")
                url = match.group("url")
                pagination[f"{rel}_url"] = url
                page_match = _PAGE_PARAM.search(url)
                if page_match:
                    pagination[f"{rel}_page"] = int(page_match.group(1))

        if pagination:
            wrapped["pagination"] = pagination

        return wrapped

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses from the API.

        GitHub signals primary rate limiting with HTTP 403 (not 429) plus
        ``x-ratelimit-remaining: 0``; both cases map to RateLimitError.

        Args:
            response: HTTP response

        Raises:
            Various UserError subclasses based on error type
        """
        status_code = response.status_code

        error_msg: str = "Unknown error"
        try:
            error_body = response.json()
            if isinstance(error_body, dict):
                raw_msg = error_body.get("message", error_body.get("error"))
                if isinstance(raw_msg, (dict, str, int, float)):
                    error_msg = str(raw_msg)
            else:
                error_msg = str(error_body)
        except ValueError:
            error_msg = response.text[:200] if response.text else "Unknown error"

        rate_remaining = response.headers.get("x-ratelimit-remaining")

        if status_code == 429 or (status_code == 403 and rate_remaining == "0"):
            retry_after = response.headers.get("retry-after")
            if retry_after is None:
                retry_after = response.headers.get("x-ratelimit-reset")
            raise RateLimitError(int(retry_after) if retry_after else None)

        if status_code in (401, 403):
            raise PermissionDeniedError("Valid token with required scopes")
        if status_code == 404:
            raise NotFoundError(error_msg)

        raise GitHubApiError(status_code, error_msg)

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> dict[str, Any]:
        """Make a GET request.

        Args:
            path: API path
            params: Query parameters
            accept: Optional Accept header override (e.g.,
                "application/vnd.github.diff" to retrieve a diff)
        """
        return await self._request("GET", path, params=params, accept=accept)

    async def post(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        return await self._request("POST", path, params=params, json_data=json_data)

    async def put(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PUT request."""
        return await self._request("PUT", path, json_data=json_data)

    async def patch(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PATCH request."""
        return await self._request("PATCH", path, json_data=json_data)

    async def delete(self, path: str) -> dict[str, Any]:
        """Make a DELETE request."""
        return await self._request("DELETE", path)


_client: GitHubClient | None = None


def get_client() -> GitHubClient:
    """Get the global GitHub client instance."""
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client
