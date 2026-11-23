"""Organization Actions settings tools.

Tools for the organization's fork pull request contributor approval policy
and for organization Actions policies (the event and actor restrictions that
GitHub's ``pull_request_target`` default block honours).

``org`` is required on every function and never falls back to
GITHUB_DEFAULT_ORG.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..client import get_client
from ..models import (
    ALL_PATTERN,
    ENFORCEMENTS,
    clamp_per_page,
    validate_choice,
    validate_name,
    validate_patterns,
    validate_positive_int,
    validate_text,
)

FORK_PR_APPROVAL_POLICIES = (
    "first_time_contributors_new_to_github",
    "first_time_contributors",
    "all_external_contributors",
)

ALLOWED_EVENTS = frozenset(
    {
        "branch_protection_rule",
        "check_run",
        "check_suite",
        "create",
        "delete",
        "deployment",
        "deployment_status",
        "discussion",
        "discussion_comment",
        "fork",
        "gollum",
        "image_version",
        "issue_comment",
        "issues",
        "label",
        "merge_group",
        "milestone",
        "page_build",
        "project",
        "project_card",
        "project_column",
        "public",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "pull_request_target",
        "push",
        "registry_package",
        "release",
        "repository_dispatch",
        "schedule",
        "status",
        "watch",
        "workflow_call",
        "workflow_dispatch",
        "workflow_run",
    }
)

MAX_ACTORS = 100
_INCLUDE_SPECIALS = frozenset({ALL_PATTERN})


class AllowedActor(BaseModel):
    """An actor allowed to trigger workflows under a restrict_actions_actors rule."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[
        "User",
        "Bot",
        "Team",
        "BusinessTeam",
        "EnterpriseTeam",
        "IntegrationInstallation",
        "App",
        "RepositoryRole",
    ]


def _validate_policy_name(name: str) -> str:
    return validate_text(name.strip() if isinstance(name, str) else name, "name")


def _condition(prefix: str, include: list[str] | None, exclude: list[str] | None) -> dict[str, Any]:
    """An include/exclude condition; GitHub needs at least one pattern in a changed one."""
    inc = validate_patterns(include, f"{prefix}_include", _INCLUDE_SPECIALS) or []
    exc = validate_patterns(exclude, f"{prefix}_exclude") or []
    if not inc and not exc:
        raise ValueError(f"{prefix} needs at least one include or exclude pattern")
    return {"include": inc, "exclude": exc}


def _repository_condition(
    include: list[str] | None, exclude: list[str] | None, protected: bool | None
) -> dict[str, Any]:
    condition = _condition("repository_name", include, exclude)
    if protected is not None:
        if not isinstance(protected, bool):
            raise ValueError("repository_name_protected must be a boolean")
        condition["protected"] = protected
    return condition


def _build_rules(
    allowed_events: list[str] | None, allowed_actors: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if allowed_events is not None:
        if not isinstance(allowed_events, list) or not allowed_events:
            raise ValueError("allowed_events must be a non-empty list")
        events = list(dict.fromkeys(allowed_events))
        for event in events:
            if event not in ALLOWED_EVENTS:
                raise ValueError(f"unknown event in allowed_events: {event!r}")
        rules.append({"type": "restrict_action_events", "parameters": {"allowed_events": events}})
    if allowed_actors is not None:
        if not isinstance(allowed_actors, list) or not allowed_actors:
            raise ValueError("allowed_actors must be a non-empty list")
        if len(allowed_actors) > MAX_ACTORS:
            raise ValueError(f"allowed_actors must have at most {MAX_ACTORS} entries")
        actors = [AllowedActor.model_validate(a).model_dump() for a in allowed_actors]
        rules.append({"type": "restrict_actions_actors", "parameters": {"allowed_actors": actors}})
    return rules


def _trim_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: policy.get(key)
        for key in (
            "id",
            "name",
            "target",
            "source_type",
            "source",
            "enforcement",
            "conditions",
            "rules",
            "updated_at",
        )
    }


async def get_org_fork_pr_approval(org: str) -> dict[str, Any]:
    """Get the organization's fork pull request contributor approval policy.

    Args:
        org: Organization name (required; no default is applied)

    Returns:
        Dict with org and approval_policy
    """
    org = validate_name(org, "org")
    client = get_client()
    result = await client.get(f"/orgs/{org}/actions/permissions/fork-pr-contributor-approval")
    return {"org": org, "approval_policy": result.get("approval_policy")}


async def set_org_fork_pr_approval(
    org: str,
    approval_policy: Literal[
        "first_time_contributors_new_to_github",
        "first_time_contributors",
        "all_external_contributors",
    ],
) -> dict[str, Any]:
    """Set the organization's fork pull request contributor approval policy.

    GitHub answers 204 to the change; the policy is read back and returned.

    Args:
        org: Organization name (required; no default is applied)
        approval_policy: One of first_time_contributors_new_to_github,
            first_time_contributors, all_external_contributors

    Returns:
        Dict with org and the approval_policy read back from GitHub
    """
    org = validate_name(org, "org")
    if approval_policy not in FORK_PR_APPROVAL_POLICIES:
        raise ValueError(f"approval_policy must be one of: {', '.join(FORK_PR_APPROVAL_POLICIES)}")
    path = f"/orgs/{org}/actions/permissions/fork-pr-contributor-approval"
    client = get_client()
    await client.put(path, json_data={"approval_policy": approval_policy})
    result = await client.get(path)
    return {"org": org, "approval_policy": result.get("approval_policy")}


async def list_org_actions_policies(
    org: str,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    """List the organization's Actions policies.

    Args:
        org: Organization name (required; no default is applied)
        page: Page number (default: 1)
        per_page: Results per page (default: 30, max: 100)

    Returns:
        Dict with policies (id, name, target, source_type, source,
        enforcement, conditions, rules, updated_at) and pagination info
    """
    org = validate_name(org, "org")
    page = validate_positive_int(page, "page")
    client = get_client()
    result = await client.get(
        f"/orgs/{org}/actions/policies",
        params={"per_page": clamp_per_page(per_page), "page": page},
    )
    items = result.get("items")
    if items is None:
        items = result.get("policies", [])
    out: dict[str, Any] = {"policies": [_trim_policy(p) for p in items]}
    if "pagination" in result:
        out["pagination"] = result["pagination"]
    return out


async def get_org_actions_policy(org: str, policy_id: int) -> dict[str, Any]:
    """Get one organization Actions policy.

    Args:
        org: Organization name (required; no default is applied)
        policy_id: Policy ID

    Returns:
        Policy (id, name, target, source_type, source, enforcement,
        conditions, rules, updated_at)
    """
    org = validate_name(org, "org")
    policy_id = validate_positive_int(policy_id, "policy_id")
    client = get_client()
    result = await client.get(f"/orgs/{org}/actions/policies/{policy_id}")
    return _trim_policy(result)


async def create_org_actions_policy(
    org: str,
    name: str,
    enforcement: Literal["disabled", "active", "evaluate"],
    repository_name_include: list[str],
    repository_name_exclude: list[str] | None = None,
    repository_name_protected: bool | None = None,
    workflow_path_include: list[str] | None = None,
    workflow_path_exclude: list[str] | None = None,
    allowed_events: list[str] | None = None,
    allowed_actors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create an organization Actions policy.

    Patterns may use letters, digits and ``. _ - / * ? [ ] ~``. ``~ALL``
    means every repository (or workflow) and is only valid as the sole
    include entry. The workflow_path condition is sent only when a
    workflow_path_* argument is given (then both keys are sent); otherwise
    the policy covers all workflows.

    Args:
        org: Organization name (required; no default is applied)
        name: Policy name (1-100 characters)
        enforcement: disabled, active or evaluate
        repository_name_include: Repository name patterns to include
        repository_name_exclude: Repository name patterns to exclude
        repository_name_protected: Limit to protected repositories
        workflow_path_include: Workflow file path patterns to include
        workflow_path_exclude: Workflow file path patterns to exclude
        allowed_events: Events workflows may run on (restrict_action_events)
        allowed_actors: Actors, each {"id": int, "type": ...}
            (restrict_actions_actors). At least one of allowed_events and
            allowed_actors is required.

    Returns:
        Created policy (id, name, target, source_type, source, enforcement,
        conditions, rules, updated_at)
    """
    org = validate_name(org, "org")
    body: dict[str, Any] = {
        "name": _validate_policy_name(name),
        "enforcement": validate_choice(enforcement, ENFORCEMENTS, "enforcement"),
    }
    conditions: dict[str, Any] = {
        "repository_name": _repository_condition(
            repository_name_include, repository_name_exclude, repository_name_protected
        )
    }
    if workflow_path_include is not None or workflow_path_exclude is not None:
        conditions["workflow_path"] = _condition(
            "workflow_path", workflow_path_include, workflow_path_exclude
        )
    body["conditions"] = conditions
    if allowed_events is None and allowed_actors is None:
        raise ValueError("at least one of allowed_events or allowed_actors is required")
    body["rules"] = _build_rules(allowed_events, allowed_actors)

    client = get_client()
    result = await client.post(f"/orgs/{org}/actions/policies", json_data=body)
    return _trim_policy(result)


async def update_org_actions_policy(
    org: str,
    policy_id: int,
    name: str | None = None,
    enforcement: Literal["disabled", "active", "evaluate"] | None = None,
    repository_name_include: list[str] | None = None,
    repository_name_exclude: list[str] | None = None,
    repository_name_protected: bool | None = None,
    workflow_path_include: list[str] | None = None,
    workflow_path_exclude: list[str] | None = None,
    allowed_events: list[str] | None = None,
    allowed_actors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update an organization Actions policy, sending only what is given.

    If any repository_name_* argument is given, repository_name_include is
    required and the repository_name condition is sent whole. If either
    workflow_path_* argument is given, both its keys are sent. If
    allowed_events or allowed_actors is given, ``rules`` is sent and REPLACES
    the policy's stored rules entirely: pass everything the policy should
    keep. At least one field must be given.

    Args:
        org: Organization name (required; no default is applied)
        policy_id: Policy ID
        name: New policy name (1-100 characters)
        enforcement: disabled, active or evaluate
        repository_name_include: Repository name patterns to include
        repository_name_exclude: Repository name patterns to exclude
        repository_name_protected: Limit to protected repositories
        workflow_path_include: Workflow file path patterns to include
        workflow_path_exclude: Workflow file path patterns to exclude
        allowed_events: Events workflows may run on (replaces stored rules)
        allowed_actors: Actors, each {"id": int, "type": ...} (replaces
            stored rules)

    Returns:
        Updated policy (id, name, target, source_type, source, enforcement,
        conditions, rules, updated_at)
    """
    org = validate_name(org, "org")
    policy_id = validate_positive_int(policy_id, "policy_id")
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = _validate_policy_name(name)
    if enforcement is not None:
        body["enforcement"] = validate_choice(enforcement, ENFORCEMENTS, "enforcement")

    conditions: dict[str, Any] = {}
    if (
        repository_name_include is not None
        or repository_name_exclude is not None
        or repository_name_protected is not None
    ):
        if repository_name_include is None:
            raise ValueError("repository_name_include is required when changing repository_name")
        conditions["repository_name"] = _repository_condition(
            repository_name_include, repository_name_exclude, repository_name_protected
        )
    if workflow_path_include is not None or workflow_path_exclude is not None:
        conditions["workflow_path"] = _condition(
            "workflow_path", workflow_path_include, workflow_path_exclude
        )
    if conditions:
        body["conditions"] = conditions

    if allowed_events is not None or allowed_actors is not None:
        body["rules"] = _build_rules(allowed_events, allowed_actors)

    if not body:
        raise ValueError("at least one field to update is required")

    client = get_client()
    result = await client.put(f"/orgs/{org}/actions/policies/{policy_id}", json_data=body)
    return _trim_policy(result)
