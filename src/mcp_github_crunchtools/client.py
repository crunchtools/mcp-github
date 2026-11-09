"""GitHub API client with security hardening.

This module provides a secure async HTTP client for the GitHub REST API.
All requests go through this client to ensure consistent security practices.
"""

import ipaddress
import json
import logging
import re
import time
from importlib.metadata import version
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp.server.dependencies import get_http_headers

from .config import get_config
from .errors import (
    ConfigurationError,
    GitHubApiError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    request_token,
)

logger = logging.getLogger(__name__)


def _retry_after_seconds(headers: httpx.Headers) -> int | None:
    """Seconds until a rate-limited call may be retried.

    ``retry-after`` is already a duration; ``x-ratelimit-reset`` is the UTC
    epoch second the window resets, so it is converted to a duration.
    """
    try:
        if (retry_after := headers.get("retry-after")) is not None:
            return max(0, int(retry_after))
        if (reset := headers.get("x-ratelimit-reset")) is not None:
            return max(0, int(reset) - int(time.time()))
    except ValueError:
        return None
    return None


MAX_RESPONSE_SIZE = 10 * 1024 * 1024
BODY_SNIPPET_CHARS = 200
ELLIPSIS = "..."


def _body_snippet(body: bytes) -> str:
    """A short, single-line excerpt of a response body, for an error message."""
    prefix = body[: BODY_SNIPPET_CHARS * 4]
    collapsed = " ".join(prefix.decode("utf-8", errors="replace").split())
    if not collapsed:
        return "<empty body>"
    if len(collapsed) > BODY_SNIPPET_CHARS or len(body) > len(prefix):
        return collapsed[: BODY_SNIPPET_CHARS - len(ELLIPSIS)] + ELLIPSIS
    return collapsed


# Query parameters whose value is a secret rather than part of the request.
# `access_token` is GitHub's own retired query-string auth, and an Enterprise
# host in front of a proxy can take any of these.
REDACTED_PARAMS = frozenset({"access_token", "client_secret", "code", "token"})


def _safe_url(url: httpx.URL) -> httpx.URL:
    """A URL fit to appear in an error message (Layer 1).

    Userinfo first: it carries its secret before the path, where redacting
    query parameters never reaches it. The rest is redacted by name, because
    `per_page`, `state` and `sha` are the diagnosis.
    """
    url = url.copy_with(userinfo=b"")
    for name in REDACTED_PARAMS & set(url.params):
        url = url.copy_set_param(name, "***")
    return url


def _where(response: httpx.Response) -> str:
    """Which request a response answered, for an error message.

    The requested URL rather than the path: `GITHUB_API_BASE_URL` points this
    client at github.com or at an Enterprise host, and a base URL that answers
    with a login page is not something a path alone can describe.
    """
    return (
        f"{response.request.method} {_safe_url(response.request.url)} "
        f"(HTTP {response.status_code}, {response.headers.get('content-type', 'no content-type')})"
    )


# Identify this client by name. httpx otherwise sends `python-httpx/<version>`,
# which bot protection answers with an HTML challenge page instead of the API --
# the failure that cost an afternoon on mcp-wordpress (RT #1596). GitHub also
# asks API clients to send one. The version comes from installed package
# metadata so it cannot drift from pyproject.toml.
USER_AGENT = (
    f"mcp-github-crunchtools/{version('mcp-github-crunchtools')} "
    "(+https://github.com/crunchtools/mcp-github)"
)
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


# An incoming Authorization header is used only in exactly this form: the
# scheme in any case, one space, then one run of printable non-space ASCII.
# The length bound is far above any GitHub token and keeps junk out.
_BEARER = re.compile(r"(?i:bearer) ([\x21-\x7e]{1,1024})")


def _incoming_token() -> str | None:
    """The token of the current HTTP request's ``Authorization: Bearer`` header.

    Returns None when there is no HTTP request (stdio) or the request has no
    Authorization header. FastMCP strips that header unless asked for it.

    Raises:
        ConfigurationError: If the header is present but not exactly
            ``Bearer <token>``. The value is never echoed.
    """
    value = get_http_headers(include={"authorization"}).get("authorization")
    if value is None:
        return None
    match = _BEARER.fullmatch(value)
    if match is None:
        raise ConfigurationError(
            "Refusing the request's Authorization header: expected 'Bearer <token>'"
        )
    return match.group(1)


_LINK_ENTRY = re.compile(r'<(?P<url>[^>]+)>;\s*rel="(?P<rel>[^"]+)"')
_PAGE_PARAM = re.compile(r"[?&]page=(\d+)")


class GitHubClient:
    """Async HTTP client for the GitHub REST API.

    Security features:
    - Configurable base URL with HTTPS enforcement (supports GHES)
    - Token passed via Authorization: Bearer header (not URL), chosen per
      call: the token of the incoming HTTP request when
      GITHUB_ACCEPT_REQUEST_TOKEN is on and the request has one, otherwise
      GITHUB_TOKEN. The shared client never holds a request's token.
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
            headers = {
                "Accept": DEFAULT_ACCEPT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": USER_AGENT,
            }
            if self._config.token:
                headers["Authorization"] = f"Bearer {self._config.token}"
            self._client = httpx.AsyncClient(
                base_url=self._config.api_base_url,
                headers=headers,
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                verify=self._config.ssl_verify,
                # This client carries the token on every request, so it must
                # never follow a redirect to another host by itself.
                follow_redirects=False,
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        """Per-call Authorization header, or {} to use the client's default.

        The request's token, when accepted and present, is returned as a
        header for this call only and recorded in the ``request_token``
        context variable so that errors scrub it.

        Raises:
            ConfigurationError: If the incoming header is malformed, or there
                is neither a request token nor GITHUB_TOKEN.
        """
        if self._config.accept_request_token:
            token = _incoming_token()
            request_token.set(token)
            if token is not None:
                return {"Authorization": f"Bearer {token}"}
        if self._config.token:
            return {}
        raise ConfigurationError(
            "No GitHub token for this request: send 'Authorization: Bearer <token>' "
            "or set GITHUB_TOKEN"
        )

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
    ) -> tuple[httpx.Response, bytes]:
        """Send one authenticated API request and return it with its bounded body.

        Transport failures and oversized responses are raised as
        GitHubApiError; the HTTP status is left for the caller to judge.

        Streamed rather than read whole, because the cap has to hold while the
        body arrives. The `content-length` check this replaces was the only
        limit on the JSON path, and GitHub does not always send that header --
        the job-log download below has always read in bounded pieces, which is
        what made the gap easy to miss.
        """
        # Resolved before anything else, so a call with no usable token makes
        # no request at all.
        headers = self._auth_headers()
        if accept:
            headers["Accept"] = accept

        client = await self._get_client()

        logger.debug("API request: %s %s", method, path)

        try:
            request = client.build_request(
                method=method,
                url=path,
                params=params,
                json=json_data,
                headers=headers or None,
            )
            response = await client.send(request, stream=True)
            try:
                body = await self._read_capped(response)
            finally:
                await response.aclose()
        except httpx.TimeoutException as e:
            raise GitHubApiError(0, f"Request timeout: {e}") from e
        except httpx.RequestError as e:
            raise GitHubApiError(0, f"Request failed: {e}") from e

        return response, body

    @staticmethod
    async def _read_capped(response: httpx.Response) -> bytes:
        """Read the body, aborting as soon as it would pass MAX_RESPONSE_SIZE.

        One buffer, measured before the copy: `aiter_bytes()` promises nothing
        about chunk size -- one chunk can be the whole body -- so appending
        first would copy in exactly the response being refused.
        """
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_SIZE:
            raise GitHubApiError(
                response.status_code,
                f"{_where(response)} declared {declared} bytes, over the "
                f"{MAX_RESPONSE_SIZE} byte limit",
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_SIZE:
                raise GitHubApiError(
                    response.status_code,
                    f"{_where(response)} sent over the {MAX_RESPONSE_SIZE} byte limit",
                )
            body += chunk
        return bytes(body)

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
        response, body = await self._send(method, path, params, json_data, accept)

        if not response.is_success:
            self._handle_error_response(response, body)

        if response.status_code == 204:
            return {"status": "deleted"}

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return {"content": body.decode("utf-8", errors="replace")}

        try:
            parsed = json.loads(body)
        except ValueError as e:
            raise GitHubApiError(
                response.status_code,
                f"{_where(response)} is not JSON ({e}): {_body_snippet(body)}",
            ) from e

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

    def _handle_error_response(self, response: httpx.Response, body: bytes) -> None:
        """Handle error responses from the API.

        GitHub signals primary rate limiting with HTTP 403 (not 429) plus
        ``x-ratelimit-remaining: 0``; both cases map to RateLimitError.

        Args:
            response: HTTP response
            body: its bounded body, already read

        Raises:
            Various UserError subclasses based on error type
        """
        status_code = response.status_code

        error_msg: str = ""
        try:
            error_body = json.loads(body)
            if isinstance(error_body, dict):
                raw_msg = error_body.get("message", error_body.get("error"))
                if isinstance(raw_msg, (dict, str, int, float)):
                    error_msg = str(raw_msg)[: BODY_SNIPPET_CHARS * 4]
            else:
                error_msg = str(error_body)[: BODY_SNIPPET_CHARS * 4]
        except ValueError:
            error_msg = ""
        # A body that is not GitHub's JSON error shape is quoted with the
        # request it answered: that is what tells an Enterprise login page or a
        # proxy apart from the API refusing something.
        error_msg = error_msg or f"{_where(response)} returned {_body_snippet(body)}"

        rate_remaining = response.headers.get("x-ratelimit-remaining")

        if status_code == 429 or (status_code == 403 and rate_remaining == "0"):
            raise RateLimitError(_retry_after_seconds(response.headers))

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
        response, body = await self._send("GET", path)
        if not response.is_redirect:
            if not response.is_success:
                self._handle_error_response(response, body)
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
