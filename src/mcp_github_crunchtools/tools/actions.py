"""GitHub Actions tools.

Tools for listing workflow runs and re-running CI on GitHub Actions.
"""

from typing import Any

from ..client import get_client
from ..models import (
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
)


async def list_workflow_runs(
    owner: str | None,
    repo: str,
    branch: str | None = None,
    status: str | None = None,
    per_page: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """List GitHub Actions workflow runs for a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        branch: Filter by head branch name
        status: Filter by status or conclusion (e.g., "completed",
            "in_progress", "queued", "failure", "success")
        per_page: Results per page, max 100 (default: 20)
        page: Page number (default: 1)

    Returns:
        Trimmed list of workflow runs with pagination info
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")

    params: dict[str, Any] = {
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status

    client = get_client()
    result = await client.get(
        f"/repos/{owner}/{repo}/actions/runs", params=params
    )

    runs = result.get("workflow_runs", [])
    items = [
        {
            "id": run.get("id"),
            "name": run.get("name"),
            "head_branch": run.get("head_branch"),
            "event": run.get("event"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "html_url": run.get("html_url"),
            "created_at": run.get("created_at"),
        }
        for run in runs
    ]

    return {
        "total_count": result.get("total_count", len(items)),
        "items": items,
    }


async def rerun_workflow_run(
    owner: str | None,
    repo: str,
    run_id: int,
) -> dict[str, Any]:
    """Re-run all jobs in a GitHub Actions workflow run.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        run_id: Workflow run ID

    Returns:
        A confirmation dict: {"status": "rerun_requested", "run_id": run_id}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    run_id = validate_positive_int(run_id, "run_id")

    client = get_client()
    await client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun")
    return {"status": "rerun_requested", "run_id": run_id}


async def rerun_failed_jobs(
    owner: str | None,
    repo: str,
    run_id: int,
) -> dict[str, Any]:
    """Re-run only the failed jobs in a GitHub Actions workflow run.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        run_id: Workflow run ID

    Returns:
        A confirmation dict: {"status": "rerun_requested", "run_id": run_id}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    run_id = validate_positive_int(run_id, "run_id")

    client = get_client()
    await client.post(
        f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs"
    )
    return {"status": "rerun_requested", "run_id": run_id}
