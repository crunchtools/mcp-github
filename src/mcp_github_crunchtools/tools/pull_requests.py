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


def _classify_checks(
    check_runs: dict[str, Any], combined_status: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Sort check-runs and commit-status contexts into verdict buckets.

    Check-run conclusions failure/cancelled/timed_out/action_required are
    failures; skipped/neutral are skips (NOT failures); success passes. An
    incomplete run, or any other completed conclusion, is pending. Commit
    statuses map failure/error -> failing, pending -> pending, success ->
    passed.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "failing": [],
        "pending": [],
        "skipped": [],
        "passed": [],
    }

    for run in check_runs.get("check_runs", []):
        name = run.get("name")
        status = run.get("status")
        if status != "completed":
            buckets["pending"].append({"name": name, "status": status})
            continue
        match run.get("conclusion"):
            case (
                "failure" | "cancelled" | "timed_out" | "action_required"
            ) as conclusion:
                url = run.get("html_url") or run.get("details_url") or ""
                buckets["failing"].append(
                    {"name": name, "conclusion": conclusion, "url": url}
                )
            case ("skipped" | "neutral") as conclusion:
                buckets["skipped"].append({"name": name, "conclusion": conclusion})
            case "success":
                buckets["passed"].append({"name": name})
            case _:
                buckets["pending"].append({"name": name, "status": status})

    for ctx in combined_status.get("statuses", []):
        name = ctx.get("context")
        match ctx.get("state"):
            case ("failure" | "error") as state:
                url = ctx.get("target_url") or ""
                buckets["failing"].append(
                    {"name": name, "conclusion": state, "url": url}
                )
            case "pending":
                buckets["pending"].append({"name": name, "status": "pending"})
            case "success":
                buckets["passed"].append({"name": name})

    return buckets


async def get_pull_request_checks(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get a CI verdict for a pull request that distinguishes skip from fail.

    Resolves the PR head SHA, then classifies every check-run (GitHub Checks
    API) and legacy commit-status context into exactly one bucket: passed,
    failing, pending, or skipped.

    IMPORTANT: SKIPPED checks (conclusion "skipped" or "neutral") are NOT
    failures and do not block merging. The legacy combined commit status can
    report an overall state of "failure" when checks are merely skipped, which
    is why this tool classifies each check explicitly instead of trusting that
    aggregate. Use the ``ready_to_merge`` boolean as the signal for whether the
    PR is clear to merge: it is True only when there are no failing and no
    pending checks and the PR is not known-unmergeable.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        A verdict with the head SHA, mergeability, per-bucket check lists, a
        summary count, and the ``ready_to_merge`` signal
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

    buckets = _classify_checks(check_runs, combined_status)
    failing = buckets["failing"]
    pending = buckets["pending"]
    skipped = buckets["skipped"]
    passed = buckets["passed"]

    mergeable = pr.get("mergeable")
    ready_to_merge = (
        not failing and not pending and mergeable is not False
    )

    return {
        "pull_number": pull_number,
        "head_sha": sha,
        "mergeable": mergeable,
        "mergeable_state": pr.get("mergeable_state", ""),
        "ready_to_merge": ready_to_merge,
        "summary": {
            "passed": len(passed),
            "failing": len(failing),
            "pending": len(pending),
            "skipped": len(skipped),
        },
        "failing": failing,
        "pending": pending,
        "skipped": skipped,
        "passed": passed,
    }
