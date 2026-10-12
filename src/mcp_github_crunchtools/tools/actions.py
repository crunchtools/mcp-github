"""GitHub Actions tools.

Tools for listing and inspecting workflow runs, reading the logs of failed
jobs, triggering fresh runs, and re-running CI on GitHub Actions.
"""

import re
from typing import Any

from ..client import GitHubClient, get_client
from ..models import (
    MAX_PER_PAGE,
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
    validate_ref,
    validate_workflow_inputs,
)

# A run's jobs are read at MAX_PER_PAGE per request, up to this many.
MAX_RUN_JOBS = 3 * MAX_PER_PAGE

DEFAULT_LOG_TAIL_LINES = 200
MAX_LOG_TAIL_LINES = 1000
# Logs are returned for at most this many failed jobs of one run, and all the
# log text of one result together stays within MAX_LOG_TOTAL_BYTES.
MAX_FAILED_JOB_LOGS = 5
MAX_LOG_TOTAL_BYTES = 256 * 1024
FAILED_JOB_CONCLUSIONS = frozenset({"failure", "timed_out"})

# CSI sequences (colours, cursor movement), OSC sequences, two-byte escapes,
# and any ESC left over from a sequence that was cut off.
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\^_])?")
# The UTC timestamp GitHub puts in front of every log line.
_LOG_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")


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
    result = await client.get(f"/repos/{owner}/{repo}/actions/runs", params=params)

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

    GitHub rejects re-runs of runs created more than 30 days ago with a 403
    ("Unable to retry this workflow run because it was created over a month
    ago"). That is NOT a permission problem: it surfaces as a GitHubApiError
    carrying GitHub's message, not a PermissionDeniedError (which is reserved
    for 401). To force a fresh build regardless of age, use trigger_workflow.

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

    As with rerun_workflow_run, GitHub rejects re-runs of runs older than 30
    days with a 403 that surfaces as a GitHubApiError (GitHub's message
    preserved), not a PermissionDeniedError. Use trigger_workflow to force a
    fresh build regardless of age.

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
    await client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs")
    return {"status": "rerun_requested", "run_id": run_id}


async def _list_run_jobs(
    client: GitHubClient, owner: str, repo: str, run_id: int
) -> tuple[list[dict[str, Any]], bool]:
    """Read the jobs of a run's latest attempt, up to MAX_RUN_JOBS.

    Returns the jobs and whether the run has more than were read.
    """
    jobs: list[dict[str, Any]] = []
    total = 0
    for page in range(1, MAX_RUN_JOBS // MAX_PER_PAGE + 1):
        result = await client.get(
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            params={"per_page": MAX_PER_PAGE, "page": page},
        )
        batch = result.get("jobs", [])
        jobs.extend(batch)
        total = result.get("total_count", len(jobs))
        if not batch or len(jobs) >= total:
            break
    return jobs, len(jobs) < total


async def get_workflow_run(
    owner: str | None,
    repo: str,
    run_id: int,
) -> dict[str, Any]:
    """Get one GitHub Actions workflow run and its jobs. No logs.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        run_id: Workflow run ID

    Returns:
        The run's status, conclusion, head SHA and branch, event and URL,
        plus its jobs (id, name, status, conclusion). ``jobs_truncated`` is
        True when the run has more jobs than are listed.
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    run_id = validate_positive_int(run_id, "run_id")

    client = get_client()
    run = await client.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}")
    jobs, jobs_truncated = await _list_run_jobs(client, owner, repo, run_id)

    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_sha": run.get("head_sha"),
        "head_branch": run.get("head_branch"),
        "event": run.get("event"),
        "html_url": run.get("html_url"),
        "jobs": [
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
            }
            for job in jobs
        ],
        "jobs_truncated": jobs_truncated,
    }


def _tail_log(download: dict[str, Any], tail_lines: int, max_bytes: int) -> dict[str, Any]:
    """Clean a downloaded log tail and cut it to tail_lines and max_bytes.

    ANSI escapes and the leading timestamp of each line are removed. The
    result is marked truncated when the byte limits left fewer lines than
    were asked for.
    """
    lines = download["content"].lstrip("\ufeff").split("\n")
    if download["truncated"]:
        # The download's start was dropped mid-line; so is its first line.
        lines = lines[1:]
    if lines and not lines[-1]:
        lines.pop()

    short = download["truncated"] and len(lines) < tail_lines
    text = "\n".join(
        _LOG_TIMESTAMP.sub("", _ANSI_ESCAPE.sub("", line.rstrip("\r")))
        for line in lines[-tail_lines:]
    )

    encoded = text.encode()
    if len(encoded) > max_bytes:
        short = True
        # Keep the end, then drop what is left of the line the cut landed in
        # (unless that one line is all there is).
        kept = encoded[-max_bytes:].decode("utf-8", errors="ignore")
        text = kept.partition("\n")[2] or kept

    return {
        "log": text,
        "log_lines": text.count("\n") + 1 if text else 0,
        "truncated": short,
    }


async def get_failed_job_logs(
    owner: str | None,
    repo: str,
    run_id: int,
    tail_lines: int = DEFAULT_LOG_TAIL_LINES,
) -> dict[str, Any]:
    """Get the end of the log of each failed job in a workflow run.

    A job counts as failed when its conclusion is "failure" or "timed_out".
    For each, the last ``tail_lines`` lines of its log are returned with ANSI
    escapes and the per-line timestamps removed, along with the names of the
    steps that failed.

    Limits, each reported in the result when it applies: ``tail_lines`` is
    capped at 1000 (the value used is returned); logs are fetched for at most
    5 failed jobs (``failed_jobs_omitted`` counts the rest); and all log text
    together stays within 256 KiB, split evenly between the jobs (a job whose
    log was cut short of ``tail_lines`` has ``truncated`` set). Only the first
    300 jobs of a run are examined: when ``jobs_truncated`` is set the run has
    more, and the failed-job counts cover only those examined.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        run_id: Workflow run ID
        tail_lines: Lines to return from the end of each log (default 200,
            max 1000)

    Returns:
        {"run_id", "tail_lines", "failed_job_count", "failed_jobs_omitted",
        "jobs_truncated", "truncated", "jobs": [{"id", "name", "conclusion",
        "html_url", "failed_steps", "log", "log_lines", "truncated"}]}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    run_id = validate_positive_int(run_id, "run_id")
    if tail_lines < 1:
        tail_lines = DEFAULT_LOG_TAIL_LINES
    tail_lines = min(tail_lines, MAX_LOG_TAIL_LINES)

    client = get_client()
    jobs, jobs_truncated = await _list_run_jobs(client, owner, repo, run_id)
    failed = [job for job in jobs if job.get("conclusion") in FAILED_JOB_CONCLUSIONS]
    selected = failed[:MAX_FAILED_JOB_LOGS]

    results: list[dict[str, Any]] = []
    for job in selected:
        job_id = validate_positive_int(job.get("id", 0), "job id")
        download = await client.get_redirected_tail(
            f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            tail_bytes=MAX_LOG_TOTAL_BYTES,
        )
        results.append(
            {
                "id": job_id,
                "name": job.get("name"),
                "conclusion": job.get("conclusion"),
                "html_url": job.get("html_url"),
                "failed_steps": [
                    step.get("name")
                    for step in job.get("steps") or []
                    if step.get("conclusion") in FAILED_JOB_CONCLUSIONS
                ],
                **_tail_log(download, tail_lines, MAX_LOG_TOTAL_BYTES // len(selected)),
            }
        )

    failed_jobs_omitted = len(failed) - len(selected)
    return {
        "run_id": run_id,
        "tail_lines": tail_lines,
        "failed_job_count": len(failed),
        "failed_jobs_omitted": failed_jobs_omitted,
        "jobs_truncated": jobs_truncated,
        "truncated": (
            jobs_truncated
            or failed_jobs_omitted > 0
            or any(entry["truncated"] for entry in results)
        ),
        "jobs": results,
    }
