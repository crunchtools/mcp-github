"""GitHub API client with security hardening.

This module provides a secure async HTTP client for the GitHub REST API.
All requests go through this client to ensure consistent security practices.
"""

import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlparse

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
# A job log is streamed and only its tail is kept, so it may be larger than a
# buffered API response; past this the download is abandoned.
MAX_DOWNLOAD_SIZE = 2 * MAX_RESPONSE_SIZE
REQUEST_TIMEOUT = 30.0
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_ACCEPT = "application/vnd.github+json"


# A last label that is a number (decimal, or hex with 0x) makes the whole host
# an IPv4 address to a resolver: "2130706433", "127.1" and "0x7f.0.0.1" are all
# loopback. This is the WHATWG URL rule for telling an address from a name.
_NUMERIC_LABEL = re.compile(r"(?:0[xX][0-9a-fA-F]*|[0-9]+)")


def _is_ip_literal(host: str) -> bool:
    """Whether a URL host is an IP address, in any spelling, rather than a name."""
    if _NUMERIC_LABEL.fullmatch(host.rstrip(".").rpartition(".")[2]):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


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
    - Redirects never followed with the token attached (see get_redirected_tail)
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
                # This client carries the token on every request, so it must
                # never follow a redirect to another host by itself.
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """Send one authenticated API request and return the raw response.

        Transport failures and oversized responses are raised as
        GitHubApiError; the HTTP status is left for the caller to judge.
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

        return response

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
            GitHubApiError: On API errors, including non-rate-limit 403s
                (e.g. re-running a workflow run older than 30 days), whose
                original GitHub message is preserved so callers can tell a
                real scope problem from other 403 conditions
            RateLimitError: On rate limiting
            PermissionDeniedError: On 401 authorization failures
            NotFoundError: When the resource does not exist
        """
        response = await self._send(method, path, params, json_data, accept)

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
            raise GitHubApiError(response.status_code, f"Invalid JSON response: {e}") from e

        if isinstance(parsed, list):
            return self._wrap_list_response(parsed, response)

        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    def _wrap_list_response(self, items: list[Any], response: httpx.Response) -> dict[str, Any]:
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

        if status_code == 401:
            raise PermissionDeniedError("Valid token with required scopes")
        if status_code == 403:
            raise GitHubApiError(status_code, error_msg)
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

    async def get_redirected_tail(self, path: str, tail_bytes: int) -> dict[str, Any]:
        """GET an endpoint that redirects to a download; return the body's tail.

        GitHub serves a job log as a 302 to a short-lived, pre-signed URL on
        a storage host. The first hop goes through the authenticated client,
        which does not follow redirects. The second hop uses a separate client
        that has no default headers, so the token is never sent to the storage
        host. That hop must be HTTPS, is itself not redirected further, and is
        streamed so that only the last ``tail_bytes`` are held in memory.

        The redirect URL carries a signature: it is never logged and never
        put in an error message.

        The target host is deliberately not checked against a list of names.
        GitHub documents no stable set of log-storage hosts (they have
        changed, and a GitHub Enterprise Server uses whatever storage its
        operator configured), so a list would break the tool without
        protecting anything: the Location is produced by the configured API
        over verified TLS and no tool argument reaches it, and whoever could
        forge that response already receives the token on every API request.
        What is refused is what no real storage endpoint looks like: anything
        but HTTPS, embedded credentials, and an IP address in place of a
        host name, which is how a forged redirect would address an internal
        service or a cloud metadata endpoint directly.

        Args:
            path: API path that answers with a redirect
            tail_bytes: How many trailing bytes of the download to keep

        Returns:
            {"content": text, "truncated": bool}; truncated is True when the
            download was longer than ``tail_bytes`` and its start was dropped.

        Raises:
            GitHubApiError: If the API does not redirect, the target is not a
                plain HTTPS URL to a named host, or the download fails or is
                too large
            RateLimitError, PermissionDeniedError, NotFoundError: As for any
                API request, from the first hop
        """
        response = await self._send("GET", path)
        if not response.is_redirect:
            if not response.is_success:
                self._handle_error_response(response)
            raise GitHubApiError(response.status_code, "Expected a redirect to a download")

        location = response.headers.get("location", "")
        target = urlparse(location)
        host = target.hostname or ""
        if (
            target.scheme != "https"
            or not host
            or _is_ip_literal(host)
            or target.username
            or target.password
        ):
            raise GitHubApiError(0, "Refusing a download redirect that is not plain HTTPS")

        tail = bytearray()
        received = 0
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(REQUEST_TIMEOUT),
                    verify=self._config.ssl_verify,
                    follow_redirects=False,
                ) as storage,
                storage.stream("GET", location) as download,
            ):
                if download.status_code != 200:
                    raise GitHubApiError(download.status_code, "Download failed")
                async for chunk in download.aiter_bytes():
                    received += len(chunk)
                    if received > MAX_DOWNLOAD_SIZE:
                        raise GitHubApiError(0, "Response too large")
                    tail += chunk
                    # Trim only once the buffer has doubled, so that the bytes
                    # kept are moved once per tail_bytes received, not per chunk.
                    if len(tail) > 2 * tail_bytes:
                        del tail[:-tail_bytes]
        # "from None": the httpx exception names the signed URL.
        except httpx.TimeoutException:
            raise GitHubApiError(0, "Download timed out") from None
        except httpx.RequestError:
            raise GitHubApiError(0, "Download failed") from None

        del tail[:-tail_bytes]
        return {
            "content": tail.decode("utf-8", errors="replace"),
            "truncated": received > len(tail),
        }

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
