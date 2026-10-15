"""Tests for the required-checks gate in merge_pull_request.

A mock GitHub answers the endpoints the gate reads; every request is
recorded, so a test can assert that a refused merge never reached the merge
endpoint.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.conftest import _patch_transport

HEAD = "a" * 40
OTHER = "b" * 40
ACTIONS_APP = 15368
MERGE_PATH = "/repos/o/r/pulls/12/merge"


def run(
    name: str,
    conclusion: str | None = "success",
    status: str = "completed",
    run_id: int = 1,
    app_id: int = ACTIONS_APP,
) -> dict[str, Any]:
    """A check run as GitHub returns it."""
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"id": app_id},
    }


def ruleset(*contexts: str | tuple[str, int]) -> dict[str, Any]:
    """A required_status_checks rule; a tuple names the integration too."""
    checks = []
    for context in contexts:
        if isinstance(context, tuple):
            checks.append({"context": context[0], "integration_id": context[1]})
        else:
            checks.append({"context": context})
    return {
        "type": "required_status_checks",
        "ruleset_id": 1,
        "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": checks,
        },
    }


class MockGitHub:
    """Routes the gate's requests; paginates check runs, statuses and rules.

    ``fail`` maps a route name (pull, rules, classic, check_runs, statuses,
    merge) to the status code and message that route answers with instead.
    """

    def __init__(
        self,
        rules: list[dict[str, Any]] | None = None,
        classic: tuple[int, dict[str, Any]] = (404, {"message": "Branch not protected"}),
        check_runs: list[dict[str, Any]] | None = None,
        statuses: list[dict[str, Any]] | None = None,
        page_size: int = 100,
        base: str = "main",
        fail: dict[str, tuple[int, str]] | None = None,
        moved: dict[str, str] | None = None,
    ) -> None:
        self.rules = rules or []
        self.classic = classic
        self.check_runs = check_runs or []
        self.statuses = statuses or []
        self.page_size = page_size
        self.base = base
        self.fail = fail or {}
        # Head and base the PR reports from its second read on, to simulate
        # a push or a retarget while the gate runs.
        self.moved = moved or {}
        self.pull_reads = 0
        self.requests: list[httpx.Request] = []
        self.routes: list[tuple[str, str, str, Callable[[httpx.Request], httpx.Response]]] = [
            ("merge", "PUT", re.escape(MERGE_PATH), self._merge),
            ("pull", "GET", r"/repos/o/r/pulls/12", self._pull),
            ("rules", "GET", r"/repos/o/r/rules/branches/.+", self._rules),
            ("classic", "GET", r"/repos/o/r/branches/.+", self._classic),
            ("check_runs", "GET", rf"/repos/o/r/commits/{HEAD}/check-runs", self._check_runs),
            ("statuses", "GET", rf"/repos/o/r/commits/{HEAD}/status", self._statuses),
        ]

    def _page(self, request: httpx.Request, items: list[dict[str, Any]]) -> tuple[list[Any], bool]:
        page = int(request.url.params.get("page", "1"))
        start = (page - 1) * self.page_size
        return items[start : start + self.page_size], start + self.page_size < len(items)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for name, method, pattern, handler in self.routes:
            if request.method == method and re.fullmatch(pattern, request.url.path):
                failure = self.fail.get(name)
                if failure is None:
                    return handler(request)
                return httpx.Response(failure[0], json={"message": failure[1]})
        return httpx.Response(404, json={"message": f"unexpected {request.url.path}"})

    def _merge(self, _request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": True, "sha": "c" * 40, "message": "Merged"})

    def _pull(self, _request: httpx.Request) -> httpx.Response:
        self.pull_reads += 1
        later = self.moved if self.pull_reads > 1 else {}
        body = {
            "number": 12,
            "head": {"sha": later.get("head", HEAD)},
            "base": {"ref": later.get("base", self.base)},
        }
        return httpx.Response(200, json=body)

    def _rules(self, request: httpx.Request) -> httpx.Response:
        items, more = self._page(request, self.rules)
        next_page = int(request.url.params.get("page", "1")) + 1
        link = f'<https://api.github.com{request.url.path}?page={next_page}>; rel="next"'
        return httpx.Response(200, json=items, headers={"link": link} if more else {})

    def _classic(self, _request: httpx.Request) -> httpx.Response:
        # ``classic`` is the required-status-checks object and its status; a
        # 404 stands for an unprotected branch, as the old endpoint said it.
        code, checks = self.classic
        if code == 404:
            return httpx.Response(200, json={"name": self.base, "protected": False})
        if code != 200:
            return httpx.Response(code, json=checks)
        protection = {"enabled": True, "required_status_checks": checks}
        return httpx.Response(200, json={"protected": True, "protection": protection})

    def _check_runs(self, request: httpx.Request) -> httpx.Response:
        items, _ = self._page(request, self.check_runs)
        return httpx.Response(200, json={"total_count": len(self.check_runs), "check_runs": items})

    def _statuses(self, request: httpx.Request) -> httpx.Response:
        items, _ = self._page(request, self.statuses)
        body = {"state": "x", "total_count": len(self.statuses), "statuses": items}
        return httpx.Response(200, json=body)

    @property
    def merges(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "PUT"]

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


async def merge(github: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> dict[str, Any]:
    from mcp_github_crunchtools.tools import merge_pull_request

    with _patch_transport(github):
        return await merge_pull_request(owner="o", repo="r", pull_number=12, **kwargs)


async def refused(github: MockGitHub, **kwargs: Any) -> str:
    """Run a merge that must be refused; return the refusal message."""
    from mcp_github_crunchtools.errors import MergeRefusedError

    with pytest.raises(MergeRefusedError) as exc_info:
        await merge(github, **kwargs)
    assert github.merges == []
    return str(exc_info.value)


class TestMergeGate:
    async def test_all_green_merges_pinned_to_head(self) -> None:
        github = MockGitHub(
            rules=[ruleset("test", ("Gatehouse triage", ACTIONS_APP), "lint")],
            check_runs=[
                run("test", run_id=1),
                run("Gatehouse triage", run_id=2),
                run("unrequired", conclusion="failure", run_id=3),
            ],
            statuses=[{"context": "lint", "state": "success"}],
        )

        result = await merge(github, merge_method="squash")

        assert result == {
            "merged": True,
            "sha": "c" * 40,
            "message": "Merged",
            "head_sha": HEAD,
            "required_checks": ["Gatehouse triage", "lint", "test"],
        }
        (put,) = github.merges
        assert put.url.path == MERGE_PATH
        assert json.loads(put.content) == {"merge_method": "squash", "sha": HEAD}
        assert github.paths()[-1] == MERGE_PATH

    @pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
    async def test_skipped_and_neutral_pass(self, conclusion: str) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test", conclusion)])

        assert (await merge(github))["merged"] is True

    @pytest.mark.parametrize(
        "conclusion", ["failure", "cancelled", "timed_out", "action_required", "stale", None]
    )
    async def test_failing_check_run_refused(self, conclusion: str | None) -> None:
        github = MockGitHub(
            rules=[ruleset("test", "build")],
            check_runs=[run("test", run_id=1), run("build", conclusion, run_id=2)],
        )

        message = await refused(github)

        assert f"build: failed (check run concluded {conclusion})" in message
        assert "test:" not in message

    @pytest.mark.parametrize("status", ["queued", "in_progress", "waiting"])
    async def test_pending_check_run_refused(self, status: str) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test", None, status=status)])

        assert f"test: pending (check run {status})" in await refused(github)

    async def test_missing_check_refused(self) -> None:
        github = MockGitHub(rules=[ruleset("test", "build")], check_runs=[run("test")])

        message = await refused(github)

        assert "build: missing" in message

    @pytest.mark.parametrize(
        ("state", "reason"),
        [
            ("pending", "pending (status pending)"),
            ("failure", "failed (status failure)"),
            ("error", "failed (status error)"),
        ],
    )
    async def test_commit_status_not_success_refused(self, state: str, reason: str) -> None:
        github = MockGitHub(
            rules=[ruleset("ci/legacy")], statuses=[{"context": "ci/legacy", "state": state}]
        )

        assert f"ci/legacy: {reason}" in await refused(github)

    async def test_every_offending_check_listed(self) -> None:
        github = MockGitHub(
            rules=[ruleset("a", "b", "c", "d")],
            check_runs=[
                run("a", "failure", run_id=1),
                run("b", None, "in_progress", 2),
                run("d", run_id=3),
            ],
        )

        message = await refused(github)

        assert "a: failed" in message
        assert "b: pending" in message
        assert "c: missing" in message
        assert "d:" not in message

    async def test_most_recent_run_of_a_name_decides(self) -> None:
        """A re-run that passed after a failure counts; the reverse does not."""
        passed_last = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[run("test", run_id=9), run("test", "failure", run_id=4)],
        )
        assert (await merge(passed_last))["merged"] is True

        failed_last = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[run("test", run_id=4), run("test", "failure", run_id=9)],
        )
        assert "test: failed" in await refused(failed_last)

    async def test_integration_id_requires_that_app(self) -> None:
        """A run of the right name from another app does not satisfy the rule,
        and neither does a commit status."""
        github = MockGitHub(
            rules=[ruleset(("Gatehouse triage", ACTIONS_APP))],
            check_runs=[run("Gatehouse triage", app_id=999)],
            statuses=[{"context": "Gatehouse triage", "state": "success"}],
        )

        assert f"missing (no check run from app {ACTIONS_APP}" in await refused(github)

    async def test_no_required_checks_refused(self) -> None:
        github = MockGitHub(rules=[{"type": "pull_request", "parameters": {}}])

        message = await refused(github)

        assert "requires no status checks" in message
        assert "allow_no_required_checks" in message

    async def test_no_required_checks_allowed_with_flag(self) -> None:
        github = MockGitHub()

        result = await merge(github, allow_no_required_checks=True)

        assert result["merged"] is True
        assert result["required_checks"] == []
        assert not any("check-runs" in p for p in github.paths())

    async def test_flag_does_not_waive_existing_checks(self) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test", "failure")])

        assert "test: failed" in await refused(github, allow_no_required_checks=True)

    async def test_caller_sha_mismatch_refused(self) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test")])

        message = await refused(github, sha=OTHER)

        assert f"head is {HEAD}" in message
        assert github.paths() == ["/repos/o/r/pulls/12"]

    @pytest.mark.parametrize("moved", [{"base": "release"}, {"head": OTHER}])
    async def test_head_or_base_moving_during_gate_refused(self, moved: dict[str, str]) -> None:
        """A retarget or push between the first read and the merge is refused."""
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test")], moved=moved)

        assert "changed while its checks were read" in await refused(github)
        assert github.pull_reads == 2

    async def test_caller_sha_matching_head_merges(self) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test")])

        assert (await merge(github, sha=HEAD.upper()))["head_sha"] == HEAD

    async def test_classic_protection_checks_enforced(self) -> None:
        github = MockGitHub(
            classic=(
                200,
                {
                    "strict": True,
                    "contexts": ["old"],
                    "checks": [
                        {"context": "old", "app_id": -1},
                        {"context": "build", "app_id": ACTIONS_APP},
                    ],
                },
            ),
            check_runs=[run("old")],
        )

        message = await refused(github)

        assert "build: missing (no check run from app" in message
        assert "old:" not in message

    async def test_classic_contexts_only(self) -> None:
        github = MockGitHub(
            classic=(200, {"contexts": ["ci/legacy"]}),
            statuses=[{"context": "ci/legacy", "state": "success"}],
        )

        assert (await merge(github))["required_checks"] == ["ci/legacy"]

    async def test_rulesets_and_classic_combined(self) -> None:
        github = MockGitHub(
            rules=[ruleset("test")],
            classic=(200, {"contexts": ["build"]}),
            check_runs=[run("test")],
        )

        assert "build: missing" in await refused(github)

    async def test_protection_403_refused_not_treated_as_none(self) -> None:
        github = MockGitHub(
            classic=(403, {"message": "Resource not accessible by personal access token"}),
        )

        message = await refused(github, allow_no_required_checks=True)

        assert "cannot read the branch protection" in message

    async def test_protection_read_from_branch_not_admin_endpoint(self) -> None:
        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test")])

        await merge(github)

        assert not any("/protection" in r.url.path for r in github.requests)

    async def test_protected_branch_without_protection_shown_refused(self) -> None:
        github = MockGitHub(check_runs=[run("test")])
        github.routes.insert(
            0,
            (
                "classic",
                "GET",
                r"/repos/o/r/branches/.+",
                lambda _r: httpx.Response(200, json={"protected": True}),
            ),
        )

        message = await refused(github, allow_no_required_checks=True)

        assert "protected but its protection is not shown" in message

    async def test_branch_404_refused_not_treated_as_unprotected(self) -> None:
        github = MockGitHub(check_runs=[run("test")], fail={"classic": (404, "Branch not found")})

        message = await refused(github, allow_no_required_checks=True)

        assert "cannot read the branch protection" in message

    async def test_second_pr_read_failing_is_not_merged(self) -> None:
        from mcp_github_crunchtools.errors import UserError

        github = MockGitHub(rules=[ruleset("test")], check_runs=[run("test")])
        # The first read is the real one (it counts pull_reads); every later
        # read fails.
        replies: list[Callable[[httpx.Request], httpx.Response]] = [
            github._pull,
            lambda _r: httpx.Response(502, json={"message": "Bad gateway"}),
        ]

        def pull(request: httpx.Request) -> httpx.Response:
            return replies[github.pull_reads](request)

        github.routes.insert(0, ("pull", "GET", r"/repos/o/r/pulls/12", pull))

        with pytest.raises(UserError):
            await merge(github)

        assert github.merges == []

    async def test_base_branch_is_encoded(self) -> None:
        github = MockGitHub(base="release/1.2", rules=[ruleset("test")], check_runs=[run("test")])

        await merge(github)

        raw = [r.url.raw_path.decode() for r in github.requests]
        assert "/repos/o/r/rules/branches/release%2F1.2?per_page=100&page=1" in raw

    async def test_check_runs_paginated(self) -> None:
        """A required run on a later page is found."""
        filler = [run(f"other-{i}", run_id=i) for i in range(1, 6)]
        github = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[*filler, run("test", run_id=50)],
            page_size=2,
        )

        assert (await merge(github))["merged"] is True
        pages = [r.url.params["page"] for r in github.requests if "check-runs" in r.url.path]
        assert pages == ["1", "2", "3"]

    async def test_failure_on_a_later_page_found(self) -> None:
        github = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[
                run("test", run_id=1),
                run("x", run_id=2),
                run("test", "failure", run_id=3),
            ],
            page_size=2,
        )

        assert "test: failed" in await refused(github)

    async def test_rules_paginated(self) -> None:
        github = MockGitHub(
            rules=[ruleset("a"), {"type": "deletion"}, ruleset("b")],
            check_runs=[run("a", run_id=1)],
            page_size=1,
        )

        assert "b: missing" in await refused(github)

    async def test_statuses_paginated(self) -> None:
        github = MockGitHub(
            rules=[ruleset("s3")],
            statuses=[{"context": f"s{i}", "state": "success"} for i in range(1, 4)],
            page_size=2,
        )

        assert (await merge(github))["merged"] is True

    async def test_too_many_pages_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mcp_github_crunchtools.tools.pull_requests as pr_mod

        monkeypatch.setattr(pr_mod, "MERGE_GATE_MAX_PAGES", 2)
        github = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[run("test", run_id=i) for i in range(1, 6)],
            page_size=2,
        )

        assert "more than 2 pages" in await refused(github)

    async def test_pr_without_head_refused(self) -> None:
        from mcp_github_crunchtools.errors import MergeRefusedError
        from mcp_github_crunchtools.tools import merge_pull_request

        def backend(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"number": 12, "head": {}, "base": {"ref": "main"}})

        with _patch_transport(backend), pytest.raises(MergeRefusedError, match="head and base"):
            await merge_pull_request(owner="o", repo="r", pull_number=12)

    @pytest.mark.parametrize(
        ("status_code", "message"),
        [
            (405, "Pull Request is not mergeable"),
            (409, "Head branch was modified. Review and try the merge again."),
        ],
    )
    async def test_github_refusal_keeps_message(self, status_code: int, message: str) -> None:
        """Not mergeable (405) and a head moved after the check (409)."""
        from mcp_github_crunchtools.errors import GitHubApiError

        github = MockGitHub(
            rules=[ruleset("test")],
            check_runs=[run("test")],
            fail={"merge": (status_code, message)},
        )

        with pytest.raises(GitHubApiError) as exc_info:
            await merge(github)

        assert f"{status_code}: {message}" in str(exc_info.value)

    async def test_newest_status_of_a_context_decides(self) -> None:
        """Duplicate statuses for a context: the newest (highest id) decides,
        whatever order GitHub lists them in."""
        older_ok = {"id": 1, "context": "ci/legacy", "state": "success"}
        newer_bad = {"id": 2, "context": "ci/legacy", "state": "failure"}
        for statuses in ([newer_bad, older_ok], [older_ok, newer_bad]):
            github = MockGitHub(rules=[ruleset("ci/legacy")], statuses=statuses)
            assert "ci/legacy: failed (status failure)" in await refused(github)

        newer_ok = {"id": 3, "context": "ci/legacy", "state": "success"}
        github = MockGitHub(rules=[ruleset("ci/legacy")], statuses=[newer_bad, newer_ok])
        assert (await merge(github))["merged"] is True

    @pytest.mark.parametrize(
        ("route", "code"),
        [("rules", 403), ("rules", 500), ("check_runs", 403), ("statuses", 500), ("pull", 404)],
    )
    async def test_unreadable_gate_data_never_merges(self, route: str, code: int) -> None:
        from mcp_github_crunchtools.errors import UserError

        github = MockGitHub(
            rules=[ruleset("test")], check_runs=[run("test")], fail={route: (code, "nope")}
        )

        with pytest.raises(UserError) as exc_info:
            await merge(github)

        if route != "pull":
            assert "Refusing to merge: could not read" in str(exc_info.value)

        assert github.merges == []


class TestMergeTool:
    """The registered MCP tool exposes and forwards the gate's argument."""

    async def test_tool_forwards_allow_no_required_checks(self) -> None:
        from fastmcp.exceptions import ToolError

        from mcp_github_crunchtools.server import mcp

        tools = {tool.name: tool for tool in await mcp.list_tools()}
        schema = tools["merge_pull_request_tool"].parameters["properties"]
        assert schema["allow_no_required_checks"]["default"] is False

        github = MockGitHub()
        arguments = {"owner": "o", "repo": "r", "pull_number": 12}
        with _patch_transport(github):
            with pytest.raises(ToolError, match="requires no status checks"):
                await mcp.call_tool("merge_pull_request_tool", arguments)
            assert github.merges == []
            await mcp.call_tool(
                "merge_pull_request_tool", {**arguments, "allow_no_required_checks": True}
            )
        assert len(github.merges) == 1
