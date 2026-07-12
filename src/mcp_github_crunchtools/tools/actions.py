"""GitHub Actions tools.

Tools for listing workflow runs, triggering fresh runs, and re-running CI
on GitHub Actions.
"""

from typing import Any

from ..client import get_client
from ..models import (
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
    validate_ref,
    validate_workflow_inputs,
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


async def trigger_workflow(
    owner: str | None,
    repo: str,
    workflow_id: str,
    ref: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger a fresh GitHub Actions run via the workflow_dispatch event.

    Unlike ``rerun_workflow_run`` (which re-runs an *existing* run and is
    rejected by GitHub with a 403 for runs created more than 30 days ago),
    this dispatches a brand-new run, so it works no matter how long ago the
    workflow last ran. The target workflow's YAML must declare an
    ``on: workflow_dispatch`` trigger.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        workflow_id: Workflow file name (e.g. "build.yml") or its numeric ID
        ref: Git ref (branch or tag) to run on. Defaults to the
            repository's default branch when omitted.
        inputs: Optional workflow_dispatch inputs as name/value pairs

    Returns:
        A confirmation dict:
        {"status": "dispatch_requested", "workflow": ..., "ref": ...}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    workflow_id = validate_name(workflow_id, "workflow_id")

    client = get_client()

    if ref is None or not ref.strip():
        repo_info = await client.get(f"/repos/{owner}/{repo}")
        ref = repo_info.get("default_branch", "main")
    ref = validate_ref(ref)

    body: dict[str, Any] = {"ref": ref}
    if inputs:
        body["inputs"] = validate_workflow_inputs(inputs)

    await client.post(
        f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
        json_data=body,
    )
    return {"status": "dispatch_requested", "workflow": workflow_id, "ref": ref}


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
