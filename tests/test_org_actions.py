"""Tests for organization Actions settings tools."""

from typing import Any, cast

import pytest

from mcp_github_crunchtools.errors import GitHubApiError
from mcp_github_crunchtools.tools.org_actions import (
    create_org_actions_policy,
    get_org_actions_policy,
    get_org_fork_pr_approval,
    list_org_actions_policies,
    set_org_fork_pr_approval,
    update_org_actions_policy,
)

from .conftest import _mock_response, _patch_client, _patch_client_sequence

FORK_PATH = "/orgs/crunchtools/actions/permissions/fork-pr-contributor-approval"
POLICY = {
    "id": 7,
    "name": "p",
    "target": "organization",
    "source_type": "Organization",
    "source": "crunchtools",
    "enforcement": "active",
    "conditions": {"repository_name": {"include": ["~ALL"], "exclude": []}},
    "rules": [],
    "updated_at": "2026-11-23T00:00:00Z",
    "extra": "dropped",
}
TRIMMED = {k: v for k, v in POLICY.items() if k != "extra"}


class TestForkPrApproval:
    @pytest.mark.asyncio
    async def test_get(self) -> None:
        resp = _mock_response(json_data={"approval_policy": "first_time_contributors"})
        with _patch_client(resp) as mc:
            result = await get_org_fork_pr_approval("crunchtools")
            call = mc.return_value.build_request.call_args
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["url"] == FORK_PATH
        assert result == {"org": "crunchtools", "approval_policy": "first_time_contributors"}

    @pytest.mark.asyncio
    async def test_set_puts_then_reads_back(self) -> None:
        put = _mock_response(status_code=204)
        get = _mock_response(json_data={"approval_policy": "all_external_contributors"})
        with _patch_client_sequence(put, get) as mc:
            result = await set_org_fork_pr_approval("crunchtools", "all_external_contributors")
            calls = mc.return_value.build_request.call_args_list
            assert len(calls) == 2
            assert calls[0].kwargs["method"] == "PUT"
            assert calls[0].kwargs["url"] == FORK_PATH
            assert calls[0].kwargs["json"] == {"approval_policy": "all_external_contributors"}
            assert calls[1].kwargs["method"] == "GET"
            assert calls[1].kwargs["url"] == FORK_PATH
        assert result == {"org": "crunchtools", "approval_policy": "all_external_contributors"}

    @pytest.mark.asyncio
    async def test_set_bad_enum(self) -> None:
        with _patch_client(_mock_response(status_code=204)) as mc:
            with pytest.raises(ValueError, match="approval_policy"):
                await set_org_fork_pr_approval("crunchtools", cast("Any", "nobody"))
            mc.return_value.build_request.assert_not_called()


class TestPolicyReads:
    @pytest.mark.asyncio
    async def test_list(self) -> None:
        resp = _mock_response(
            json_data=[POLICY],
            headers={"link": '<https://api.github.com/x?page=2>; rel="next"'},
        )
        with _patch_client(resp) as mc:
            result = await list_org_actions_policies("crunchtools", page=1, per_page=500)
            call = mc.return_value.build_request.call_args
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["url"] == "/orgs/crunchtools/actions/policies"
            assert call.kwargs["params"] == {"per_page": 100, "page": 1}
        assert result["policies"] == [TRIMMED]
        assert result["pagination"]["next_page"] == 2

    @pytest.mark.asyncio
    async def test_get(self) -> None:
        with _patch_client(_mock_response(json_data=POLICY)) as mc:
            result = await get_org_actions_policy("crunchtools", 7)
            call = mc.return_value.build_request.call_args
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["url"] == "/orgs/crunchtools/actions/policies/7"
        assert result == TRIMMED


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_pull_request_target_allow(self) -> None:
        with _patch_client(_mock_response(status_code=201, json_data=POLICY)) as mc:
            result = await create_org_actions_policy(
                org="crunchtools",
                name="allow-pull-request-target-ci",
                enforcement="active",
                repository_name_include=["~ALL"],
                workflow_path_include=[".github/workflows/ci.yml"],
                allowed_events=["pull_request_target"],
            )
            call = mc.return_value.build_request.call_args
            assert call.kwargs["method"] == "POST"
            assert call.kwargs["url"] == "/orgs/crunchtools/actions/policies"
            assert call.kwargs["json"] == {
                "name": "allow-pull-request-target-ci",
                "enforcement": "active",
                "conditions": {
                    "repository_name": {"include": ["~ALL"], "exclude": []},
                    "workflow_path": {"include": [".github/workflows/ci.yml"], "exclude": []},
                },
                "rules": [
                    {
                        "type": "restrict_action_events",
                        "parameters": {"allowed_events": ["pull_request_target"]},
                    }
                ],
            }
        assert result == TRIMMED

    @pytest.mark.asyncio
    async def test_create_actors_dedup_protected_no_workflow_path(self) -> None:
        with _patch_client(_mock_response(status_code=201, json_data=POLICY)) as mc:
            await create_org_actions_policy(
                org="crunchtools",
                name=" n ",
                enforcement="evaluate",
                repository_name_include=["mcp-*"],
                repository_name_exclude=["mcp-old"],
                repository_name_protected=True,
                allowed_events=["push", "push", "schedule"],
                allowed_actors=[{"id": 5, "type": "App"}],
            )
            body = mc.return_value.build_request.call_args.kwargs["json"]
        assert body["name"] == "n"
        assert body["conditions"] == {
            "repository_name": {"include": ["mcp-*"], "exclude": ["mcp-old"], "protected": True}
        }
        assert body["rules"] == [
            {
                "type": "restrict_action_events",
                "parameters": {"allowed_events": ["push", "schedule"]},
            },
            {
                "type": "restrict_actions_actors",
                "parameters": {"allowed_actors": [{"id": 5, "type": "App"}]},
            },
        ]

    @pytest.mark.asyncio
    async def test_github_422(self) -> None:
        resp = _mock_response(status_code=422, json_data={"message": "Validation Failed"})
        with _patch_client(resp), pytest.raises(GitHubApiError, match="422: Validation Failed"):
            await create_org_actions_policy(
                "crunchtools", "n", "active", ["~ALL"], allowed_events=["push"]
            )


GOOD: dict[str, Any] = {
    "org": "crunchtools",
    "name": "n",
    "enforcement": "active",
    "repository_name_include": ["~ALL"],
    "allowed_events": ["push"],
}


def _bad(**override: Any) -> dict[str, Any]:
    return {**GOOD, **override}


class TestBadInput:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "override",
        [
            {"enforcement": "enabled"},
            {"repository_name_exclude": ["~ALL"]},
            {"repository_name_include": ["~ALL", "foo"]},
            {"workflow_path_include": ["a"], "workflow_path_exclude": ["~ALL"]},
            {"allowed_events": ["not_an_event"]},
            {"allowed_events": []},
            {"allowed_events": None},
            {"allowed_events": None, "allowed_actors": []},
            {"allowed_actors": [{"id": 0, "type": "User"}]},
            {"allowed_actors": [{"id": 1, "type": "Alien"}]},
            {"allowed_actors": [{"id": 1, "type": "User", "x": 1}]},
            {"org": None},
            {"org": ""},
            {"org": "a/b"},
            {"workflow_path_include": ["../x.yml"]},
            {"workflow_path_include": ["a b.yml"]},
            {"repository_name_include": []},
            {"repository_name_include": ["a;b"]},
            {"name": ""},
            {"name": "x" * 101},
            {"name": "a\nb"},
        ],
    )
    async def test_create_rejected_before_request(self, override: dict[str, Any]) -> None:
        with _patch_client(_mock_response(status_code=201, json_data=POLICY)) as mc:
            with pytest.raises(ValueError, match=r"\S"):
                await create_org_actions_policy(**_bad(**override))
            mc.return_value.build_request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("func", "args"),
        [
            (get_org_fork_pr_approval, (None,)),
            (get_org_fork_pr_approval, ("a/b",)),
            (set_org_fork_pr_approval, ("a/b", "first_time_contributors")),
            (list_org_actions_policies, ("a/b",)),
            (list_org_actions_policies, ("crunchtools", 0)),
            (get_org_actions_policy, ("a/b", 1)),
            (get_org_actions_policy, ("crunchtools", 0)),
            (update_org_actions_policy, ("a/b", 1, "n")),
            (update_org_actions_policy, ("crunchtools", 0, "n")),
        ],
    )
    async def test_other_functions_reject(self, func: Any, args: tuple[Any, ...]) -> None:
        with _patch_client(_mock_response(json_data={})) as mc:
            with pytest.raises(ValueError, match=r"\S"):
                await func(*args)
            mc.return_value.build_request.assert_not_called()


class TestUpdate:
    @pytest.mark.asyncio
    async def test_name_only(self) -> None:
        with _patch_client(_mock_response(json_data=POLICY)) as mc:
            result = await update_org_actions_policy("crunchtools", 7, name="new")
            call = mc.return_value.build_request.call_args
            assert call.kwargs["method"] == "PUT"
            assert call.kwargs["url"] == "/orgs/crunchtools/actions/policies/7"
            assert call.kwargs["json"] == {"name": "new"}
        assert result == TRIMMED

    @pytest.mark.asyncio
    async def test_conditions_and_rules(self) -> None:
        with _patch_client(_mock_response(json_data=POLICY)) as mc:
            await update_org_actions_policy(
                "crunchtools",
                7,
                enforcement="disabled",
                repository_name_include=["a"],
                workflow_path_exclude=["x.yml"],
                allowed_actors=[{"id": 2, "type": "Team"}],
            )
            assert mc.return_value.build_request.call_args.kwargs["json"] == {
                "enforcement": "disabled",
                "conditions": {
                    "repository_name": {"include": ["a"], "exclude": []},
                    "workflow_path": {"include": [], "exclude": ["x.yml"]},
                },
                "rules": [
                    {
                        "type": "restrict_actions_actors",
                        "parameters": {"allowed_actors": [{"id": 2, "type": "Team"}]},
                    }
                ],
            }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"repository_name_exclude": ["a"]},
            {"repository_name_protected": True},
            {"repository_name_include": ["~ALL", "b"]},
            {"allowed_events": ["bogus"]},
            {"allowed_events": []},
            {"enforcement": "nope"},
        ],
    )
    async def test_update_rejected_before_request(self, kwargs: dict[str, Any]) -> None:
        with _patch_client(_mock_response(json_data=POLICY)) as mc:
            with pytest.raises(ValueError, match=r"\S"):
                await update_org_actions_policy("crunchtools", 7, **kwargs)
            mc.return_value.build_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_github_422(self) -> None:
        resp = _mock_response(status_code=422, json_data={"message": "Validation Failed"})
        with _patch_client(resp), pytest.raises(GitHubApiError, match="422: Validation Failed"):
            await update_org_actions_policy("crunchtools", 7, name="n")


class TestActorLimit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("count", "accepted"), [(100, True), (101, False)])
    async def test_allowed_actors_boundary(self, count: int, accepted: bool) -> None:
        actors = [{"id": n, "type": "User"} for n in range(1, count + 1)]
        override = {"allowed_events": None, "allowed_actors": actors}
        with _patch_client(_mock_response(status_code=201, json_data=POLICY)) as mc:
            if accepted:
                await create_org_actions_policy(**_bad(**override))
                rules = mc.return_value.build_request.call_args.kwargs["json"]["rules"]
                assert len(rules[0]["parameters"]["allowed_actors"]) == count
            else:
                with pytest.raises(ValueError, match="at most 100"):
                    await create_org_actions_policy(**_bad(**override))
                mc.return_value.build_request.assert_not_called()
