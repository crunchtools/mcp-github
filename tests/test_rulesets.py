"""Tests for ruleset tools."""

from typing import Any

import pytest

from .conftest import _mock_response, _patch_client

FULL = {
    "id": 7,
    "name": "main protection",
    "target": "branch",
    "source_type": "Organization",
    "source": "o",
    "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [{"type": "deletion"}],
    "current_user_can_bypass": "never",
    "updated_at": "2026-01-01T00:00:00Z",
    "_links": {"dropped": True},
}
TRIMMED = {k: v for k, v in FULL.items() if k != "_links"}
EMPTY_TRIMMED = dict.fromkeys(TRIMMED)

ORG_CREATE = {
    "org": "o",
    "name": "main protection",
    "enforcement": "active",
    "ref_name_include": ["~DEFAULT_BRANCH"],
    "repository_name_include": ["~ALL"],
}


def _call(mock_client: Any) -> Any:
    return mock_client.return_value.build_request.call_args


class TestListRulesets:
    @pytest.mark.asyncio
    async def test_org_level(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import list_rulesets

        resp = _mock_response(json_data=[FULL, {"id": 8}])
        with _patch_client(resp) as mock_client:
            result = await list_rulesets(org="o")
            call = _call(mock_client)
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["url"] == "/orgs/o/rulesets"
            assert call.kwargs["params"] == {"per_page": 30, "page": 1}
        assert result == {"rulesets": [TRIMMED, {**EMPTY_TRIMMED, "id": 8}]}

    @pytest.mark.asyncio
    async def test_repo_level_with_targets_and_pagination(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import list_rulesets

        resp = _mock_response(
            json_data=[FULL],
            headers={"link": '<https://api.github.com/x?page=3>; rel="next"'},
        )
        with _patch_client(resp) as mock_client:
            result = await list_rulesets(
                org="o", repo="r", targets="branch, tag", page=2, per_page=500
            )
            call = _call(mock_client)
            assert call.kwargs["url"] == "/repos/o/r/rulesets"
            assert call.kwargs["params"] == {
                "per_page": 100,
                "page": 2,
                "targets": "branch,tag",
            }
        assert result["rulesets"] == [TRIMMED]
        assert result["pagination"]["next_page"] == 3

    @pytest.mark.asyncio
    async def test_repository_target_at_org_level(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import list_rulesets

        with _patch_client(_mock_response(json_data=[])) as mock_client:
            await list_rulesets(org="o", targets="repository")
            assert _call(mock_client).kwargs["params"]["targets"] == "repository"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            {"org": ""},
            {"org": "bad org"},
            {"org": "o", "repo": "../x"},
            {"org": "o", "targets": "bogus"},
            {"org": "o", "targets": ""},
            {"org": "o", "targets": "branch,"},
            {"org": "o", "repo": "r", "targets": "repository"},
            {"org": "o", "page": 0},
        ],
    )
    async def test_bad_input(self, arguments: dict[str, Any]) -> None:
        from mcp_github_crunchtools.tools.rulesets import list_rulesets

        with _patch_client(_mock_response(json_data=[])) as mock_client:
            with pytest.raises(ValueError, match=r".+"):
                await list_rulesets(**arguments)
            mock_client.return_value.build_request.assert_not_called()


class TestGetRuleset:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("repo", "url"),
        [(None, "/orgs/o/rulesets/7"), ("r", "/repos/o/r/rulesets/7")],
    )
    async def test_paths(self, repo: str | None, url: str) -> None:
        from mcp_github_crunchtools.tools.rulesets import get_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            result = await get_ruleset(org="o", ruleset_id=7, repo=repo)
            call = _call(mock_client)
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["url"] == url
        assert result == TRIMMED

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            {"org": "o", "ruleset_id": 0},
            {"org": "o", "ruleset_id": -3},
            {"org": "", "ruleset_id": 1},
            {"org": "o", "ruleset_id": 1, "repo": "a/b"},
        ],
    )
    async def test_bad_input(self, arguments: dict[str, Any]) -> None:
        from mcp_github_crunchtools.tools.rulesets import get_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            with pytest.raises(ValueError, match=r".+"):
                await get_ruleset(**arguments)
            mock_client.return_value.build_request.assert_not_called()


class TestCreateRuleset:
    @pytest.mark.asyncio
    async def test_org_minimal(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import create_ruleset

        with _patch_client(_mock_response(status_code=201, json_data=FULL)) as mock_client:
            result = await create_ruleset(**ORG_CREATE)
            call = _call(mock_client)
            assert call.kwargs["method"] == "POST"
            assert call.kwargs["url"] == "/orgs/o/rulesets"
            assert call.kwargs["json"] == {
                "name": "main protection",
                "target": "branch",
                "enforcement": "active",
                "conditions": {
                    "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
                    "repository_name": {"include": ["~ALL"], "exclude": []},
                },
                "rules": [],
            }
        assert result == TRIMMED

    @pytest.mark.asyncio
    async def test_repo_full(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import create_ruleset

        rules = [
            {"type": "deletion"},
            {"type": "update"},
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["squash"],
                    "required_approving_review_count": 2,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "test"},
                        {"context": "lint", "integration_id": 15368},
                    ],
                    "strict_required_status_checks_policy": True,
                },
            },
            {
                "type": "branch_name_pattern",
                "parameters": {"operator": "regex", "pattern": "^feat/"},
            },
            {
                "type": "required_deployments",
                "parameters": {"required_deployment_environments": ["prod"]},
            },
        ]
        actors = [
            {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"},
            {"actor_type": "OrganizationAdmin"},
            {"actor_type": "DeployKey", "bypass_mode": "exempt"},
        ]
        with _patch_client(_mock_response(status_code=201, json_data=FULL)) as mock_client:
            await create_ruleset(
                org="o",
                repo="r",
                name="  guard  ",
                enforcement="evaluate",
                ref_name_include=["refs/heads/main", "release/*"],
                ref_name_exclude=["wip/*"],
                bypass_actors=actors,
                rules=rules,
            )
            call = _call(mock_client)
            assert call.kwargs["url"] == "/repos/o/r/rulesets"
            assert call.kwargs["json"] == {
                "name": "guard",
                "target": "branch",
                "enforcement": "evaluate",
                "conditions": {
                    "ref_name": {
                        "include": ["refs/heads/main", "release/*"],
                        "exclude": ["wip/*"],
                    }
                },
                "bypass_actors": [
                    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"},
                    {"actor_type": "OrganizationAdmin", "bypass_mode": "always"},
                    {"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "exempt"},
                ],
                "rules": [
                    {"type": "deletion"},
                    {"type": "update", "parameters": {"update_allows_fetch_and_merge": False}},
                    {
                        "type": "pull_request",
                        "parameters": {
                            "allowed_merge_methods": ["squash"],
                            "dismiss_stale_reviews_on_push": False,
                            "require_code_owner_review": False,
                            "require_last_push_approval": False,
                            "required_approving_review_count": 2,
                            "required_review_thread_resolution": False,
                        },
                    },
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "test"},
                                {"context": "lint", "integration_id": 15368},
                            ],
                            "strict_required_status_checks_policy": True,
                            "do_not_enforce_on_create": False,
                        },
                    },
                    {
                        "type": "branch_name_pattern",
                        "parameters": {
                            "operator": "regex",
                            "pattern": "^feat/",
                            "negate": False,
                        },
                    },
                    {
                        "type": "required_deployments",
                        "parameters": {"required_deployment_environments": ["prod"]},
                    },
                ],
            }

    @pytest.mark.asyncio
    async def test_push_target_has_no_ref_name(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import create_ruleset

        with _patch_client(_mock_response(status_code=201, json_data=FULL)) as mock_client:
            await create_ruleset(
                org="o",
                name="push",
                enforcement="active",
                target="push",
                repository_name_include=["~ALL"],
                repository_name_protected=True,
            )
            assert _call(mock_client).kwargs["json"]["conditions"] == {
                "repository_name": {"include": ["~ALL"], "exclude": [], "protected": True}
            }

    @pytest.mark.asyncio
    async def test_github_422_surfaces(self) -> None:
        from mcp_github_crunchtools.errors import GitHubApiError
        from mcp_github_crunchtools.tools.rulesets import create_ruleset

        resp = _mock_response(status_code=422, json_data={"message": "Validation Failed"})
        with _patch_client(resp), pytest.raises(GitHubApiError, match="422: Validation Failed"):
            await create_ruleset(**ORG_CREATE)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "override",
        [
            {"org": ""},
            {"org": "a b"},
            {"repo": "bad repo"},
            {"name": "   "},
            {"name": "x" * 101},
            {"name": "bad\x00name"},
            {"enforcement": "on"},
            {"target": "commit"},
            {"repository_name_include": None},
            {"repository_name_include": []},
            {"ref_name_include": None},
            {"ref_name_include": ["~NOPE"]},
            {"ref_name_include": ["has space"]},
            {"ref_name_include": ["a\nb"]},
            {"ref_name_include": [""]},
            {"ref_name_include": ["x" * 256]},
            {"ref_name_include": ["a"] * 101},
            {"ref_name_exclude": ["~ALL"]},
            {"repository_name_include": ["~DEFAULT_BRANCH"]},
            {"target": "push", "ref_name_include": ["main"]},
            {"target": "repository", "ref_name_include": ["main"]},
            {"repo": "r", "target": "repository"},
            {"repo": "r", "repository_name_include": ["x"]},
            {"bypass_actors": [{"actor_type": "Team"}]},
            {"bypass_actors": [{"actor_type": "Team", "actor_id": 0}]},
            {"bypass_actors": [{"actor_type": "DeployKey", "actor_id": 3}]},
            {"bypass_actors": [{"actor_type": "DeployKey", "bypass_mode": "pull_request"}]},
            {"bypass_actors": [{"actor_type": "Robot", "actor_id": 1}]},
            {"bypass_actors": [{"actor_type": "User", "actor_id": 1, "bypass_mode": "never"}]},
            {"bypass_actors": [{"actor_type": "User", "actor_id": 1, "extra": 1}]},
            {
                "target": "tag",
                "bypass_actors": [
                    {"actor_type": "User", "actor_id": 1, "bypass_mode": "pull_request"}
                ],
            },
            {"rules": [{"type": "magic"}]},
            {"rules": [{"type": "deletion", "parameters": {}}]},
            {"rules": [{"type": "deletion"}] * 51},
            {
                "rules": [
                    {"type": "pull_request", "parameters": {"required_approving_review_count": 11}}
                ]
            },
            {"rules": [{"type": "pull_request", "parameters": {"allowed_merge_methods": []}}]},
            {"rules": [{"type": "pull_request", "parameters": {"allowed_merge_methods": ["ff"]}}]},
            {"rules": [{"type": "pull_request", "parameters": {"bogus": True}}]},
            {
                "rules": [
                    {
                        "type": "required_deployments",
                        "parameters": {"required_deployment_environments": []},
                    }
                ]
            },
            {
                "rules": [
                    {
                        "type": "required_deployments",
                        "parameters": {"required_deployment_environments": ["a b"]},
                    }
                ]
            },
            {
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"context": ""}]},
                    }
                ]
            },
            {
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"context": "a\tb"}]},
                    }
                ]
            },
            {
                "rules": [
                    {"type": "required_status_checks", "parameters": {"required_status_checks": []}}
                ]
            },
            {
                "rules": [
                    {"type": "tag_name_pattern", "parameters": {"operator": "like", "pattern": "x"}}
                ]
            },
            {
                "rules": [
                    {"type": "tag_name_pattern", "parameters": {"operator": "regex", "pattern": ""}}
                ]
            },
            {
                "rules": [
                    {
                        "type": "tag_name_pattern",
                        "parameters": {"operator": "regex", "pattern": "x" * 256},
                    }
                ]
            },
            {"rules": [{"type": "tag_name_pattern"}]},
            {"rules": ["deletion"]},
        ],
    )
    async def test_bad_input(self, override: dict[str, Any]) -> None:
        from mcp_github_crunchtools.tools.rulesets import create_ruleset

        arguments = {**ORG_CREATE, **override}
        if "repo" in override and "repository_name_include" not in override:
            arguments.pop("repository_name_include")
        if override.get("repository_name_include", 1) is None:
            arguments.pop("repository_name_include")
        if override.get("ref_name_include", 1) is None:
            arguments.pop("ref_name_include")
        with _patch_client(_mock_response(status_code=201, json_data=FULL)) as mock_client:
            with pytest.raises(ValueError, match=r".+"):
                await create_ruleset(**arguments)
            mock_client.return_value.build_request.assert_not_called()


class TestUpdateRuleset:
    @pytest.mark.asyncio
    async def test_only_given_fields_org(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            result = await update_ruleset(org="o", ruleset_id=7, enforcement="disabled")
            call = _call(mock_client)
            assert call.kwargs["method"] == "PUT"
            assert call.kwargs["url"] == "/orgs/o/rulesets/7"
            assert call.kwargs["json"] == {"enforcement": "disabled"}
        assert result == TRIMMED

    @pytest.mark.asyncio
    async def test_repo_replaces_rules_and_conditions(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            await update_ruleset(
                org="o",
                repo="r",
                ruleset_id=7,
                name="renamed",
                ref_name_include=["~DEFAULT_BRANCH"],
                ref_name_exclude=["wip/*"],
                bypass_actors=[],
                rules=[{"type": "non_fast_forward"}],
            )
            call = _call(mock_client)
            assert call.kwargs["url"] == "/repos/o/r/rulesets/7"
            assert call.kwargs["json"] == {
                "name": "renamed",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": ["wip/*"]}},
                "bypass_actors": [],
                "rules": [{"type": "non_fast_forward"}],
            }

    @pytest.mark.asyncio
    async def test_org_conditions_with_protected(self) -> None:
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            await update_ruleset(
                org="o",
                ruleset_id=7,
                ref_name_include=["~ALL"],
                repository_name_include=["mcp-*"],
                repository_name_protected=False,
            )
            assert _call(mock_client).kwargs["json"] == {
                "conditions": {
                    "ref_name": {"include": ["~ALL"], "exclude": []},
                    "repository_name": {"include": ["mcp-*"], "exclude": [], "protected": False},
                }
            }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            {"ref_name_include": ["main"]},
            {"repository_name_include": ["~ALL"]},
            {"repo": "r", "ref_name_exclude": ["wip/*"]},
        ],
    )
    async def test_a_partial_conditions_change_is_refused(
        self, arguments: dict[str, object]
    ) -> None:
        """A PUT replaces conditions whole, so a missing half would be dropped."""
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            with pytest.raises(ValueError, match="conditions change needs"):
                await update_ruleset(org="o", ruleset_id=7, **arguments)
            mock_client.return_value.build_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_github_422_surfaces(self) -> None:
        from mcp_github_crunchtools.errors import GitHubApiError
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        resp = _mock_response(status_code=422, json_data={"message": "Invalid rule"})
        with _patch_client(resp), pytest.raises(GitHubApiError, match="422: Invalid rule"):
            await update_ruleset(org="o", ruleset_id=7, enforcement="active")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            {"org": "o", "ruleset_id": 7},
            {"org": "", "ruleset_id": 7, "enforcement": "active"},
            {"org": "o", "ruleset_id": 0, "enforcement": "active"},
            {"org": "o", "ruleset_id": 7, "repo": "a b", "enforcement": "active"},
            {"org": "o", "ruleset_id": 7, "enforcement": "maybe"},
            {"org": "o", "ruleset_id": 7, "target": "nope"},
            {"org": "o", "ruleset_id": 7, "name": ""},
            {"org": "o", "ruleset_id": 7, "repo": "r", "repository_name_include": ["x"]},
            {"org": "o", "ruleset_id": 7, "repo": "r", "repository_name_protected": True},
            {"org": "o", "ruleset_id": 7, "repo": "r", "target": "repository"},
            {"org": "o", "ruleset_id": 7, "target": "push", "ref_name_exclude": ["x"]},
            {"org": "o", "ruleset_id": 7, "ref_name_include": ["bad pattern"]},
            {"org": "o", "ruleset_id": 7, "rules": [{"type": "nope"}]},
            {
                "org": "o",
                "ruleset_id": 7,
                "target": "push",
                "bypass_actors": [
                    {"actor_type": "User", "actor_id": 1, "bypass_mode": "pull_request"}
                ],
            },
        ],
    )
    async def test_bad_input(self, arguments: dict[str, Any]) -> None:
        from mcp_github_crunchtools.tools.rulesets import update_ruleset

        with _patch_client(_mock_response(json_data=FULL)) as mock_client:
            with pytest.raises(ValueError, match=r".+"):
                await update_ruleset(**arguments)
            mock_client.return_value.build_request.assert_not_called()
