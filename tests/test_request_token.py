"""Tests for the per-request GitHub token (GITHUB_ACCEPT_REQUEST_TOKEN).

An incoming HTTP request is simulated by setting FastMCP's current-request
context variable, which is what get_http_headers reads. HTTP goes through a
real httpx client over a mock transport, so the assertions are on the
Authorization header as it would be sent.
"""

import asyncio
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastmcp.server.http import _current_http_request
from starlette.requests import Request

ENV_TOKEN = "ghp_fake_env_token_0001"
REQUEST_TOKEN = "ghp_fake_request_token_0002"


@contextmanager
def incoming_request(authorization: bytes | None) -> Iterator[None]:
    """Run the block as if inside an MCP HTTP request with this header."""
    headers = [(b"content-type", b"application/json")]
    if authorization is not None:
        headers.append((b"authorization", authorization))
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    reset = _current_http_request.set(Request(scope))
    try:
        yield
    finally:
        _current_http_request.reset(reset)


class Recorder:
    """A mock GitHub that records each request and answers with an issue."""

    def __init__(self, delay: asyncio.Event | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.delay = delay

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay is not None:
            await self.delay.wait()
        return httpx.Response(200, json={"number": 1}, request=request)

    @property
    def auth(self) -> list[str | None]:
        return [r.headers.get("authorization") for r in self.requests]


@pytest.fixture
def transport() -> Generator[Callable[[Recorder], Any], None, None]:
    """Patch httpx.AsyncClient to send through a Recorder, env untouched."""
    real_client = httpx.AsyncClient
    patches: list[Any] = []

    def install(recorder: Recorder) -> Any:
        def build(**kwargs: object) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(recorder), **kwargs)

        p = patch.object(httpx, "AsyncClient", side_effect=build)
        patches.append(p)
        return p.start()

    yield install
    for p in patches:
        p.stop()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set the token environment for one test."""

    def apply(token: str | None, accept: str | None) -> None:
        for name, value in (("GITHUB_TOKEN", token), ("GITHUB_ACCEPT_REQUEST_TOKEN", accept)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

    return apply


async def _get_issue(number: int = 1) -> dict[str, Any]:
    from mcp_github_crunchtools.tools import get_issue

    return await get_issue(owner="o", repo="r", issue_number=number)


class TestConfig:
    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", " Yes "])
    def test_option_on_makes_env_token_optional(self, env: Callable[..., None], value: str) -> None:
        from mcp_github_crunchtools.config import Config

        env(None, value)
        config = Config()
        assert config.accept_request_token is True
        assert config.token is None

    @pytest.mark.parametrize("value", [None, "", "false", "0", "no", "on"])
    def test_option_off_still_requires_env_token(
        self, env: Callable[..., None], value: str | None
    ) -> None:
        from mcp_github_crunchtools.config import Config
        from mcp_github_crunchtools.errors import ConfigurationError

        env(None, value)
        with pytest.raises(ConfigurationError, match="GITHUB_TOKEN"):
            Config()


class TestTokenChoice:
    async def test_stdio_uses_env_token(self, env: Callable[..., None], transport: Any) -> None:
        """No HTTP request (stdio): the env token, option on or off."""
        env(ENV_TOKEN, "true")
        recorder = Recorder()
        transport(recorder)

        await _get_issue()

        assert recorder.auth == [f"Bearer {ENV_TOKEN}"]

    async def test_option_off_ignores_incoming_header(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        env(ENV_TOKEN, None)
        recorder = Recorder()
        transport(recorder)

        with incoming_request(f"Bearer {REQUEST_TOKEN}".encode()):
            await _get_issue()

        assert recorder.auth == [f"Bearer {ENV_TOKEN}"]

    async def test_option_off_ignores_malformed_header(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        """With the option off the header is not even parsed."""
        env(ENV_TOKEN, None)
        recorder = Recorder()
        transport(recorder)

        with incoming_request(b"Basic Zm9vOmJhcg=="):
            await _get_issue()

        assert recorder.auth == [f"Bearer {ENV_TOKEN}"]

    @pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
    async def test_option_on_uses_request_token_over_env(
        self, env: Callable[..., None], transport: Any, scheme: str
    ) -> None:
        env(ENV_TOKEN, "true")
        recorder = Recorder()
        transport(recorder)

        with incoming_request(f"{scheme} {REQUEST_TOKEN}".encode()):
            await _get_issue()

        assert recorder.auth == [f"Bearer {REQUEST_TOKEN}"]

    async def test_option_on_without_header_falls_back_to_env(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        env(ENV_TOKEN, "true")
        recorder = Recorder()
        transport(recorder)

        with incoming_request(None):
            await _get_issue()

        assert recorder.auth == [f"Bearer {ENV_TOKEN}"]

    async def test_request_token_only_instance(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        """No env token: the shared client has no default Authorization."""
        from mcp_github_crunchtools.client import get_client

        env(None, "true")
        recorder = Recorder()
        transport(recorder)

        with incoming_request(f"Bearer {REQUEST_TOKEN}".encode()):
            await _get_issue()

        assert recorder.auth == [f"Bearer {REQUEST_TOKEN}"]
        http = await get_client()._get_client()
        assert "authorization" not in http.headers

    async def test_no_token_errors_before_any_request(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        """Neither a request token nor GITHUB_TOKEN: refused, nothing sent."""
        from mcp_github_crunchtools.errors import ConfigurationError

        env(None, "true")
        recorder = Recorder()
        transport(recorder)

        with pytest.raises(ConfigurationError, match="No GitHub token for this request"):
            await _get_issue()
        with (
            incoming_request(None),
            pytest.raises(ConfigurationError, match="No GitHub token for this request"),
        ):
            await _get_issue()

        assert recorder.requests == []

    @pytest.mark.parametrize(
        "authorization",
        [
            b"",
            b"Bearer",
            b"Bearer ",
            b"Bearer  ghp_two_spaces",
            b"Bearer ghp_a ghp_b",
            b"Bearer ghp_tab\tx",
            b"Bearer ghp_ctrl\x01x",
            b"Bearer ghp_del\x7fx",
            b"Bearer ghp_latin\xe9x",
            b"Basic Zm9vOmJhcg==",
            b"token ghp_fake",
            b"ghp_no_scheme",
            b"Bearer " + b"a" * 1025,
        ],
    )
    async def test_malformed_header_refused_not_forwarded(
        self, env: Callable[..., None], transport: Any, authorization: bytes
    ) -> None:
        """A malformed header is refused, even with an env token to fall back to."""
        from mcp_github_crunchtools.errors import ConfigurationError

        env(ENV_TOKEN, "true")
        recorder = Recorder()
        transport(recorder)

        with incoming_request(authorization), pytest.raises(ConfigurationError) as exc_info:
            await _get_issue()

        assert recorder.requests == []
        assert "ghp_" not in str(exc_info.value)

    async def test_concurrent_requests_send_their_own_token(
        self, env: Callable[..., None], transport: Any
    ) -> None:
        """Two requests in flight at once each send their own token."""
        env(ENV_TOKEN, "true")
        release = asyncio.Event()
        recorder = Recorder(delay=release)
        transport(recorder)
        tokens = {n: f"ghp_fake_caller_{n:04d}" for n in range(1, 6)}

        async def call(number: int) -> None:
            with incoming_request(f"Bearer {tokens[number]}".encode()):
                await _get_issue(number)
                # And again after the others have run, from the same request.
                await _get_issue(number)

        tasks = [asyncio.create_task(call(n)) for n in tokens]
        while len(recorder.requests) < len(tokens):
            await asyncio.sleep(0)
        # Every first call is in flight before any is answered.
        release.set()
        await asyncio.gather(*tasks)

        assert len(recorder.requests) == 2 * len(tokens)
        for request in recorder.requests:
            number = int(request.url.path.rsplit("/", 1)[1])
            assert request.headers["authorization"] == f"Bearer {tokens[number]}"


class TestScrubbing:
    async def test_request_token_scrubbed_from_errors(self, env: Callable[..., None]) -> None:
        from mcp_github_crunchtools.errors import GitHubApiError

        env(ENV_TOKEN, "true")

        def echo(request: httpx.Request) -> httpx.Response:
            message = f"bad {REQUEST_TOKEN} and {ENV_TOKEN}"
            return httpx.Response(500, json={"message": message}, request=request)

        real_client = httpx.AsyncClient
        with (
            patch.object(
                httpx,
                "AsyncClient",
                side_effect=lambda **kw: real_client(transport=httpx.MockTransport(echo), **kw),
            ),
            incoming_request(f"Bearer {REQUEST_TOKEN}".encode()),
            pytest.raises(GitHubApiError) as exc_info,
        ):
            await _get_issue()

        message = str(exc_info.value)
        assert REQUEST_TOKEN not in message
        assert ENV_TOKEN not in message
        assert message.count("***") == 2

    async def test_transport_error_scrubs_request_token(self, env: Callable[..., None]) -> None:
        from mcp_github_crunchtools.errors import GitHubApiError

        env(None, "true")

        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"refused {request.headers['authorization']}")

        real_client = httpx.AsyncClient
        with (
            patch.object(
                httpx,
                "AsyncClient",
                side_effect=lambda **kw: real_client(transport=httpx.MockTransport(fail), **kw),
            ),
            incoming_request(f"Bearer {REQUEST_TOKEN}".encode()),
            pytest.raises(GitHubApiError) as exc_info,
        ):
            await _get_issue()

        assert REQUEST_TOKEN not in str(exc_info.value)
