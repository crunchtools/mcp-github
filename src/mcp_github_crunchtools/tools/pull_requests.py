"""Pull request tools.

Tools for listing, fetching, diffing, and checking GitHub pull requests.
"""

from typing import Any

from ..client import get_client
from ..errors import ValidationError
from ..models import (
    PR_STATES,
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
)

DIFF_ACCEPT = "application/vnd.github.diff"


async def list_pull_requests(
    owner: str | None,
    repo: str,
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List pull requests for a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        state: Filter by state (open, closed, all)
        per_page: Results per page (max 100)
        page: Page number

    Returns:
        List of pull requests with pagination info
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if state not in PR_STATES:
        allowed = ", ".join(sorted(PR_STATES))
        raise ValidationError(f"Invalid state. Allowed: {allowed}")

    client = get_client()

    params: dict[str, Any] = {
        "state": state,
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }

    return await client.get(f"/repos/{owner}/{repo}/pulls", params=params)


async def get_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get a single pull request by number.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        Pull request details including head/base refs and merge status
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    return await client.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")


async def get_pull_request_diff(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get the unified diff for a pull request.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        Dictionary with the diff text under the "content" key
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    return await client.get(
        f"/repos/{owner}/{repo}/pulls/{pull_number}",
        accept=DIFF_ACCEPT,
    )


async def get_pull_request_checks(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get a combined CI status summary for a pull request.

    Resolves the PR head SHA, then aggregates check-runs (GitHub Checks API)
    and the legacy combined commit status into a single summary.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        Summary with the head SHA, overall state, and per-check conclusions
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()

    pr = await client.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")
    head = pr.get("head") or {}
    sha = head.get("sha")
    if not sha:
        raise ValidationError("Could not resolve pull request head SHA")

    check_runs = await client.get(
        f"/repos/{owner}/{repo}/commits/{sha}/check-runs"
    )
    combined_status = await client.get(
        f"/repos/{owner}/{repo}/commits/{sha}/status"
    )

    runs = check_runs.get("check_runs", [])
    checks = [
        {
            "name": run.get("name"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
        }
        for run in runs
    ]

    statuses = [
        {
            "context": status.get("context"),
            "state": status.get("state"),
            "description": status.get("description"),
        }
        for status in combined_status.get("statuses", [])
    ]

    return {
        "sha": sha,
        "overall_state": combined_status.get("state"),
        "total_check_runs": check_runs.get("total_count", len(runs)),
        "check_runs": checks,
        "statuses": statuses,
    }
