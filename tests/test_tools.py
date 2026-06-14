"""Tests for MCP tools.

These tests verify tool behavior without making actual API calls.
Integration tests with a real GitHub account should be run separately.
"""

import base64

import pytest

from tests.conftest import _mock_response, _patch_client, _patch_client_sequence


class TestToolRegistration:
    """Tests to verify all tools are properly registered."""

    def test_server_exists(self) -> None:
        """Server should be importable and configured."""
        from mcp_github_crunchtools.server import mcp

        assert mcp is not None

    def test_imports(self) -> None:
        """All tool functions should be importable."""
        import mcp_github_crunchtools.tools as tools_mod
        from mcp_github_crunchtools.tools import __all__

        for name in __all__:
            func = getattr(tools_mod, name)
            assert callable(func), f"{name} is not callable"

    def test_tool_count(self) -> None:
        """Server should export exactly 11 MVP tools."""
        from mcp_github_crunchtools.tools import __all__

        assert len(__all__) == 11


class TestErrorSafety:
    """Tests to verify error messages don't leak sensitive data."""

    def test_github_api_error_sanitizes_token(self) -> None:
        """GitHubApiError should sanitize tokens from messages."""
        import os

        from mcp_github_crunchtools.errors import GitHubApiError

        os.environ["GITHUB_TOKEN"] = "ghp_secret_token_12345"

        try:
            error = GitHubApiError(401, "Invalid token: ghp_secret_token_12345")
            assert "ghp_secret_token_12345" not in str(error)
            assert "***" in str(error)
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_not_found_truncates_long_ids(self) -> None:
        """NotFoundError should truncate long identifiers."""
        from mcp_github_crunchtools.errors import NotFoundError

        long_id = "a" * 100
        error = NotFoundError(long_id)
        error_str = str(error)

        assert long_id not in error_str
        assert "..." in error_str


class TestConfigSafety:
    """Tests for configuration security."""

    def test_config_repr_hides_token(self) -> None:
        import os

        os.environ["GITHUB_TOKEN"] = "ghp_secret_test_token"

        try:
            from mcp_github_crunchtools.config import Config

            config = Config()
            assert "ghp_secret_test_token" not in repr(config)
            assert "ghp_secret_test_token" not in str(config)
            assert "***" in repr(config)
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_config_requires_token(self) -> None:
        import os

        from mcp_github_crunchtools.config import Config
        from mcp_github_crunchtools.errors import ConfigurationError

        token = os.environ.pop("GITHUB_TOKEN", None)

        try:
            with pytest.raises(ConfigurationError):
                Config()
        finally:
            if token:
                os.environ["GITHUB_TOKEN"] = token

    def test_config_default_api_url(self) -> None:
        import os

        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ.pop("GITHUB_API_URL", None)

        try:
            from mcp_github_crunchtools.config import Config

            config = Config()
            assert config.api_base_url == "https://api.github.com"
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_config_ghes_api_url(self) -> None:
        import os

        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ["GITHUB_API_URL"] = "https://ghe.example.com/api/v3"

        try:
            from mcp_github_crunchtools.config import Config

            config = Config()
            assert config.api_base_url == "https://ghe.example.com/api/v3"
        finally:
            del os.environ["GITHUB_TOKEN"]
            del os.environ["GITHUB_API_URL"]

    def test_config_rejects_http(self) -> None:
        import os

        from mcp_github_crunchtools.config import Config
        from mcp_github_crunchtools.errors import ConfigurationError

        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ["GITHUB_API_URL"] = "http://ghe.example.com"

        try:
            with pytest.raises(ConfigurationError, match="HTTPS"):
                Config()
        finally:
            del os.environ["GITHUB_TOKEN"]
            del os.environ["GITHUB_API_URL"]

    def test_config_default_org(self) -> None:
        import os

        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ["GITHUB_DEFAULT_ORG"] = "crunchtools"

        try:
            from mcp_github_crunchtools.config import Config

            config = Config()
            assert config.default_org == "crunchtools"
        finally:
            del os.environ["GITHUB_TOKEN"]
            del os.environ["GITHUB_DEFAULT_ORG"]

    def test_config_ssl_verify_default(self) -> None:
        import os

        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ.pop("GITHUB_SSL_VERIFY", None)
        os.environ.pop("SSL_CERT_FILE", None)

        try:
            from mcp_github_crunchtools.config import Config

            config = Config()
            assert config.ssl_verify is True
        finally:
            del os.environ["GITHUB_TOKEN"]


class TestClientHeadersAndAuth:
    """Tests for client auth headers."""

    @pytest.mark.asyncio
    async def test_bearer_auth_header(self) -> None:
        """Client should set a Bearer Authorization header."""
        import os

        from mcp_github_crunchtools.client import get_client

        os.environ["GITHUB_TOKEN"] = "ghp_header_test"
        try:
            client = get_client()
            http = await client._get_client()
            assert http.headers["Authorization"] == "Bearer ghp_header_test"
            assert http.headers["Accept"] == "application/vnd.github+json"
            assert http.headers["X-GitHub-Api-Version"] == "2022-11-28"
            await client.close()
        finally:
            del os.environ["GITHUB_TOKEN"]


class TestPagination:
    """Tests for Link-header pagination parsing."""

    @pytest.mark.asyncio
    async def test_link_header_parsed(self) -> None:
        """List responses should parse the Link header into pagination."""
        from mcp_github_crunchtools.tools import list_pull_requests

        link = (
            '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next", '
            '<https://api.github.com/repos/o/r/pulls?page=5>; rel="last"'
        )
        resp = _mock_response(
            json_data=[{"number": 1, "title": "PR one"}],
            headers={"link": link},
        )

        with _patch_client(resp):
            result = await list_pull_requests(owner="o", repo="r")

        assert len(result["items"]) == 1
        assert result["pagination"]["next_page"] == 2
        assert result["pagination"]["last_page"] == 5

    @pytest.mark.asyncio
    async def test_no_link_header(self) -> None:
        """Lists without a Link header should omit pagination."""
        from mcp_github_crunchtools.tools import list_pull_requests

        resp = _mock_response(json_data=[{"number": 1}])

        with _patch_client(resp):
            result = await list_pull_requests(owner="o", repo="r")

        assert "pagination" not in result


class TestIssueTools:
    """Tests for issue tools."""

    @pytest.mark.asyncio
    async def test_list_issues_filters_prs(self) -> None:
        """list_issues should drop items that are pull requests."""
        from mcp_github_crunchtools.tools import list_issues

        resp = _mock_response(
            json_data=[
                {"number": 1, "title": "Real issue"},
                {"number": 2, "title": "A PR", "pull_request": {"url": "x"}},
            ],
        )

        with _patch_client(resp):
            result = await list_issues(owner="o", repo="r")

        assert len(result["items"]) == 1
        assert result["items"][0]["number"] == 1

    @pytest.mark.asyncio
    async def test_get_issue(self) -> None:
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(json_data={"number": 42, "title": "Bug"})

        with _patch_client(resp):
            result = await get_issue(owner="o", repo="r", issue_number=42)

        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_create_issue_comment(self) -> None:
        from mcp_github_crunchtools.tools import create_issue_comment

        resp = _mock_response(
            status_code=201,
            json_data={"id": 100, "body": "Thanks!"},
        )

        with _patch_client(resp):
            result = await create_issue_comment(
                owner="o", repo="r", issue_number=42, body="Thanks!"
            )

        assert result["body"] == "Thanks!"

    @pytest.mark.asyncio
    async def test_invalid_state(self) -> None:
        from mcp_github_crunchtools.errors import ValidationError
        from mcp_github_crunchtools.tools import list_issues

        resp = _mock_response(json_data=[])
        with _patch_client(resp), pytest.raises(ValidationError):
            await list_issues(owner="o", repo="r", state="bogus")


class TestPullRequestTools:
    """Tests for pull request tools."""

    @pytest.mark.asyncio
    async def test_list_pull_requests(self) -> None:
        from mcp_github_crunchtools.tools import list_pull_requests

        resp = _mock_response(json_data=[{"number": 5, "title": "Add auth"}])

        with _patch_client(resp):
            result = await list_pull_requests(owner="o", repo="r")

        assert result["items"][0]["number"] == 5

    @pytest.mark.asyncio
    async def test_get_pull_request(self) -> None:
        from mcp_github_crunchtools.tools import get_pull_request

        resp = _mock_response(
            json_data={"number": 5, "head": {"sha": "abc"}, "state": "open"},
        )

        with _patch_client(resp):
            result = await get_pull_request(owner="o", repo="r", pull_number=5)

        assert result["number"] == 5

    @pytest.mark.asyncio
    async def test_get_pull_request_diff(self) -> None:
        """Diff should be returned as text under content."""
        from mcp_github_crunchtools.tools import get_pull_request_diff

        resp = _mock_response(
            text="diff --git a/x b/x\n@@ -1 +1 @@",
            content_type="application/vnd.github.diff; charset=utf-8",
        )

        with _patch_client(resp) as mock_client:
            result = await get_pull_request_diff(owner="o", repo="r", pull_number=5)
            call = mock_client.return_value.request.call_args
            assert call.kwargs["headers"]["Accept"] == "application/vnd.github.diff"

        assert "diff --git" in result["content"]

    @pytest.mark.asyncio
    async def test_get_pull_request_checks(self) -> None:
        """Checks should combine PR head, check-runs, and commit status."""
        from mcp_github_crunchtools.tools import get_pull_request_checks

        pr_resp = _mock_response(json_data={"number": 5, "head": {"sha": "deadbeef"}})
        runs_resp = _mock_response(
            json_data={
                "total_count": 2,
                "check_runs": [
                    {"name": "build", "status": "completed", "conclusion": "success"},
                    {"name": "test", "status": "completed", "conclusion": "failure"},
                ],
            },
        )
        status_resp = _mock_response(
            json_data={
                "state": "failure",
                "statuses": [
                    {"context": "ci/legacy", "state": "success", "description": "ok"},
                ],
            },
        )

        with _patch_client_sequence(pr_resp, runs_resp, status_resp):
            result = await get_pull_request_checks(
                owner="o", repo="r", pull_number=5
            )

        assert result["sha"] == "deadbeef"
        assert result["overall_state"] == "failure"
        assert result["total_check_runs"] == 2
        assert len(result["check_runs"]) == 2
        assert result["check_runs"][1]["conclusion"] == "failure"
        assert result["statuses"][0]["context"] == "ci/legacy"


class TestFileTools:
    """Tests for file tools."""

    @pytest.mark.asyncio
    async def test_get_file_content_decodes_base64(self) -> None:
        from mcp_github_crunchtools.tools import get_file_content

        encoded = base64.b64encode(b"# Hello\n").decode()
        resp = _mock_response(
            json_data={
                "name": "README.md",
                "path": "README.md",
                "sha": "abc",
                "size": 8,
                "encoding": "base64",
                "content": encoded,
            },
        )

        with _patch_client(resp):
            result = await get_file_content(owner="o", repo="r", path="README.md")

        assert result["text"] == "# Hello\n"

    @pytest.mark.asyncio
    async def test_get_file_content_binary(self) -> None:
        from mcp_github_crunchtools.tools import get_file_content

        encoded = base64.b64encode(b"\xff\xfe\x00\x01").decode()
        resp = _mock_response(
            json_data={
                "name": "logo.png",
                "path": "logo.png",
                "size": 4,
                "encoding": "base64",
                "content": encoded,
            },
        )

        with _patch_client(resp):
            result = await get_file_content(owner="o", repo="r", path="logo.png")

        assert result["text"] is None
        assert "binary" in result["notice"]

    @pytest.mark.asyncio
    async def test_get_file_content_rejects_traversal(self) -> None:
        from mcp_github_crunchtools.errors import ValidationError
        from mcp_github_crunchtools.tools import get_file_content

        resp = _mock_response(json_data={})
        with _patch_client(resp), pytest.raises(ValidationError, match=r"\.\."):
            await get_file_content(owner="o", repo="r", path="../etc/passwd")

    @pytest.mark.asyncio
    async def test_list_repo_tree(self) -> None:
        from mcp_github_crunchtools.tools import list_repo_tree

        resp = _mock_response(
            json_data={
                "sha": "main",
                "truncated": False,
                "tree": [
                    {"path": "src", "type": "tree"},
                    {"path": "README.md", "type": "blob"},
                ],
            },
        )

        with _patch_client(resp):
            result = await list_repo_tree(owner="o", repo="r")

        assert len(result["tree"]) == 2

    @pytest.mark.asyncio
    async def test_list_repo_tree_recursive(self) -> None:
        from mcp_github_crunchtools.tools import list_repo_tree

        resp = _mock_response(json_data={"tree": [], "truncated": False})

        with _patch_client(resp) as mock_client:
            await list_repo_tree(
                owner="o", repo="r", tree_sha="main", recursive=True
            )
            call = mock_client.return_value.request.call_args
            assert call.kwargs["params"] == {"recursive": "1"}


class TestSearchTools:
    """Tests for search tools."""

    @pytest.mark.asyncio
    async def test_search_code(self) -> None:
        from mcp_github_crunchtools.tools import search_code

        resp = _mock_response(
            json_data={"total_count": 1, "items": [{"name": "auth.py"}]},
        )

        with _patch_client(resp):
            result = await search_code(query="def login")

        assert result["total_count"] == 1

    @pytest.mark.asyncio
    async def test_search_issues(self) -> None:
        from mcp_github_crunchtools.tools import search_issues

        resp = _mock_response(
            json_data={"total_count": 2, "items": [{"number": 1}, {"number": 2}]},
        )

        with _patch_client(resp):
            result = await search_issues(query="is:open label:bug")

        assert result["total_count"] == 2

    @pytest.mark.asyncio
    async def test_empty_query(self) -> None:
        from mcp_github_crunchtools.errors import ValidationError
        from mcp_github_crunchtools.tools import search_code

        resp = _mock_response(json_data={})
        with _patch_client(resp), pytest.raises(ValidationError):
            await search_code(query="   ")


class TestClientErrorHandling:
    """Tests for HTTP client error responses."""

    @pytest.mark.asyncio
    async def test_401_raises_permission_denied(self) -> None:
        from mcp_github_crunchtools.errors import PermissionDeniedError
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(
            status_code=401,
            json_data={"message": "Bad credentials"},
        )

        with _patch_client(resp), pytest.raises(PermissionDeniedError):
            await get_issue(owner="o", repo="r", issue_number=1)

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        from mcp_github_crunchtools.errors import NotFoundError
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(
            status_code=404,
            json_data={"message": "Not Found"},
        )

        with _patch_client(resp), pytest.raises(NotFoundError):
            await get_issue(owner="o", repo="r", issue_number=99999)

    @pytest.mark.asyncio
    async def test_403_rate_limit(self) -> None:
        """403 with x-ratelimit-remaining: 0 should raise RateLimitError."""
        from mcp_github_crunchtools.errors import RateLimitError
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(
            status_code=403,
            json_data={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
        )

        with _patch_client(resp), pytest.raises(RateLimitError):
            await get_issue(owner="o", repo="r", issue_number=1)

    @pytest.mark.asyncio
    async def test_403_permission_denied_when_not_rate_limited(self) -> None:
        """403 without rate-limit signal should raise PermissionDeniedError."""
        from mcp_github_crunchtools.errors import PermissionDeniedError
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(
            status_code=403,
            json_data={"message": "Forbidden"},
            headers={"x-ratelimit-remaining": "42"},
        )

        with _patch_client(resp), pytest.raises(PermissionDeniedError):
            await get_issue(owner="o", repo="r", issue_number=1)

    @pytest.mark.asyncio
    async def test_429_rate_limit(self) -> None:
        from mcp_github_crunchtools.errors import RateLimitError
        from mcp_github_crunchtools.tools import get_issue

        resp = _mock_response(
            status_code=429,
            json_data={"message": "Too Many Requests"},
            headers={"retry-after": "60"},
        )

        with _patch_client(resp), pytest.raises(RateLimitError):
            await get_issue(owner="o", repo="r", issue_number=1)
