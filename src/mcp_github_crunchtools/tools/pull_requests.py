"""Pull request tools.

Tools for listing, fetching, diffing, checking, opening, merging, and
discussing GitHub pull requests.
"""

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..client import GitHubClient, get_client
from ..errors import (
    GitHubApiError,
    MergeRefusedError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)
from ..models import (
    MAX_PER_PAGE,
    MERGE_METHODS,
    PR_STATES,
    CreateIssueCommentInput,
    CreateIssueInput,
    clamp_per_page,
    resolve_owner,
    validate_commit_sha,
    validate_head,
    validate_name,
    validate_positive_int,
    validate_ref,
)
from .actions import MAX_RUN_JOBS

DIFF_ACCEPT = "application/vnd.github.diff"

# list_pull_request_comments reads three collections. Each is fetched at
# MAX_PER_PAGE per request up to this many items, so one call returns at most
# three times this and costs at most nine requests.
MAX_PR_COMMENTS_PER_KIND = 3 * MAX_PER_PAGE

# The merge gate reads every page of rules, check runs and statuses up to this
# many pages each. A longer list is not judged in part: the merge is refused.
MERGE_GATE_MAX_PAGES = 10

# Check-run conclusions that satisfy a required check.
PASSING_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})

# The GitHub Actions app. Every Actions job is a check run reported by it,
# with the job's id and name.
ACTIONS_APP_ID = 15368

# Where the head commit's check runs were read from. A fine-grained token
# cannot be granted Checks, so the check-runs endpoint answers it 403; the
# Actions API (Actions: read) then stands in, seeing only Actions jobs.
# How many workflow runs' jobs the Actions fallback reads at once, and how
# many runs (one per workflow and event) it reads at all.
ACTIONS_JOB_READS_AT_ONCE = 4
ACTIONS_MAX_RUNS = 30

SOURCE_CHECK_RUNS = "check-runs"
SOURCE_ACTIONS = "actions"
ACTIONS_SOURCE_NOTE = (
    "Check runs were read from the Actions API because this token cannot read "
    "check-runs (a fine-grained token cannot be granted Checks). Checks "
    "reported by apps other than GitHub Actions are not visible."
)

# A required check: its context (check-run name or status context) and, when
# the rule names one, the id of the GitHub App that must report it.
RequiredCheck = tuple[str, int | None]


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
            case ("failure" | "cancelled" | "timed_out" | "action_required") as conclusion:
                url = run.get("html_url") or run.get("details_url") or ""
                buckets["failing"].append({"name": name, "conclusion": conclusion, "url": url})
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
                buckets["failing"].append({"name": name, "conclusion": state, "url": url})
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

    truncated: list[str] = []
    check_runs, source = await _head_check_runs(client, owner, repo, sha, truncated.append)
    combined_status = await client.get(f"/repos/{owner}/{repo}/commits/{sha}/status")

    buckets = _classify_checks({"check_runs": check_runs}, combined_status)
    failing = buckets["failing"]
    pending = buckets["pending"]
    skipped = buckets["skipped"]
    passed = buckets["passed"]

    mergeable = pr.get("mergeable")
    ready_to_merge = not failing and not pending and mergeable is not False

    verdict: dict[str, Any] = {
        "pull_number": pull_number,
        "head_sha": sha,
        "mergeable": mergeable,
        "mergeable_state": pr.get("mergeable_state", ""),
        "ready_to_merge": ready_to_merge,
        "checks_source": source,
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
    if source == SOURCE_ACTIONS:
        verdict["note"] = ACTIONS_SOURCE_NOTE
    if truncated:
        # A cut list cannot clear the PR: an unread page may hold a failure.
        verdict["ready_to_merge"] = False
        verdict["truncated"] = "Not everything was read of: " + ", ".join(truncated)
    return verdict


async def update_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
    state: str | None = None,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Update a pull request — including closing or reopening it.

    Note: this does NOT merge. Set state="closed" to close a PR without merging.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        state: "open" or "closed" (set "closed" to close the PR)
        title: New title (optional)
        body: New body (optional)

    Returns:
        Updated PR details (number, state, html_url, title)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    json_data: dict[str, Any] = {}
    if state is not None:
        if state not in ("open", "closed"):
            raise ValidationError("state must be 'open' or 'closed'")
        json_data["state"] = state
    if title is not None:
        json_data["title"] = title
    if body is not None:
        json_data["body"] = body
    if not json_data:
        raise ValidationError("no fields to update")

    client = get_client()
    result = await client.patch(
        f"/repos/{owner}/{repo}/pulls/{pull_number}",
        json_data=json_data,
    )
    return {
        "number": result.get("number"),
        "state": result.get("state"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
    }


async def create_pull_request(
    owner: str | None,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
) -> dict[str, Any]:
    """Open a pull request.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        title: Pull request title (required, non-empty)
        head: Branch holding the changes; "owner:branch" for a fork
        base: Branch the changes should be merged into
        body: Pull request description (Markdown)
        draft: Open the pull request as a draft

    Returns:
        Created PR details (number, html_url, title, state, draft)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if not title or not title.strip():
        raise ValidationError("title must not be empty")
    # A pull request's title and body have the same limits as an issue's.
    validated = CreateIssueInput(title=title.strip(), body=body)

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/pulls",
        json_data={
            "title": validated.title,
            "body": validated.body,
            "head": validate_head(head),
            "base": validate_ref(base, "base"),
            "draft": draft,
        },
    )
    return {
        "number": result.get("number"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
        "state": result.get("state"),
        "draft": result.get("draft"),
    }


# Called with the path of a list that holds more than was read.
OnCut = Callable[[str], None]

API_ERRORS = (GitHubApiError, NotFoundError, PermissionDeniedError, RateLimitError)


def _refuse_cut(path: str) -> None:
    """The merge gate does not judge a list it could not read in full."""
    raise MergeRefusedError(
        f"Refusing to merge: {path} lists more than the gate reads; "
        "the checks cannot be judged in full"
    )


async def _read_pages(
    client: GitHubClient,
    path: str,
    key: str | None,
    on_cut: OnCut,
    params: dict[str, Any] | None = None,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Read up to ``max_pages`` (default MERGE_GATE_MAX_PAGES) pages of a
    list, calling ``on_cut`` if there were more; API errors propagate.

    ``key`` names the list inside an object response (``check_runs``,
    ``statuses``, ``jobs``), whose length is known from ``total_count``; None
    means the response is a bare list, paged by its Link header.
    """
    collected: list[dict[str, Any]] = []
    for page in range(1, (max_pages or MERGE_GATE_MAX_PAGES) + 1):
        query = {**(params or {}), "per_page": MAX_PER_PAGE, "page": page}
        result = await client.get(path, params=query)
        if key is None:
            items = result.get("items") or []
            more = "next_page" in result.get("pagination", {})
        else:
            items = result.get(key) or []
            more = bool(items) and len(collected) + len(items) < (result.get("total_count") or 0)
        collected.extend(item for item in items if isinstance(item, dict))
        if not more:
            return collected
    on_cut(path)
    return collected


async def _read_all(client: GitHubClient, path: str, key: str | None) -> list[dict[str, Any]]:
    """Read every page of a list for the merge gate, or refuse."""
    try:
        return await _read_pages(client, path, key, _refuse_cut)
    except API_ERRORS as e:
        raise MergeRefusedError(f"Refusing to merge: could not read {path}: {e}") from e


def _job_as_run(job: dict[str, Any]) -> dict[str, Any]:
    """An Actions job in the shape of the check run it is."""
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
        "html_url": job.get("html_url"),
        "app": {"id": ACTIONS_APP_ID},
    }


async def _actions_check_runs(
    client: GitHubClient, owner: str, repo: str, sha: str, on_cut: OnCut
) -> list[dict[str, Any]]:
    """The head commit's Actions jobs, as check runs.

    Only the newest run of each workflow and event is read: an older run's
    job is superseded by the newer run's job of the same name, and a job only
    the older run had is then missing, which refuses rather than passes. Each
    run lists the jobs of its latest attempt, up to MAX_RUN_JOBS, read
    ACTIONS_JOB_READS_AT_ONCE runs at a time. Past ACTIONS_MAX_RUNS runs, only
    the newest are read and ``on_cut`` is called.
    """
    runs_path = f"/repos/{owner}/{repo}/actions/runs"
    workflow_runs = await _read_pages(
        client, runs_path, "workflow_runs", on_cut, params={"head_sha": sha}
    )
    newest: dict[tuple[Any, Any], int] = {}
    for workflow_run in workflow_runs:
        run_id = workflow_run.get("id")
        key = (workflow_run.get("workflow_id"), workflow_run.get("event"))
        if isinstance(run_id, int) and run_id > newest.get(key, 0):
            newest[key] = run_id
    run_ids = sorted(newest.values())
    if len(run_ids) > ACTIONS_MAX_RUNS:
        on_cut(runs_path)
        run_ids = run_ids[-ACTIONS_MAX_RUNS:]
    gate = asyncio.Semaphore(ACTIONS_JOB_READS_AT_ONCE)

    async def run_jobs(run_id: int) -> list[dict[str, Any]]:
        async with gate:
            jobs_path = f"{runs_path}/{run_id}/jobs"
            pages = MAX_RUN_JOBS // MAX_PER_PAGE
            return await _read_pages(client, jobs_path, "jobs", on_cut, max_pages=pages)

    per_run = await asyncio.gather(*(run_jobs(run_id) for run_id in run_ids))
    return [_job_as_run(job) for jobs in per_run for job in jobs if job.get("head_sha") == sha]


async def _head_check_runs(
    client: GitHubClient, owner: str, repo: str, sha: str, on_cut: OnCut
) -> tuple[list[dict[str, Any]], str]:
    """The head commit's check runs and where they were read from.

    A token that may not read check-runs (any fine-grained token) gets 403
    and the Actions jobs instead; any other error propagates. The client
    maps a rate-limit 403 to RateLimitError and a 401 (a token GitHub
    rejects outright) to PermissionDeniedError, so a GitHubApiError 403 is a
    permission refusal.
    """
    path = f"/repos/{owner}/{repo}/commits/{sha}/check-runs"
    try:
        return await _read_pages(client, path, "check_runs", on_cut), SOURCE_CHECK_RUNS
    except GitHubApiError as e:
        if e.status_code != 403:
            raise
    return await _actions_check_runs(client, owner, repo, sha, on_cut), SOURCE_ACTIONS


def _app_id(value: object) -> int | None:
    """An app id from a rule, or None when any source may report the check.

    Classic branch protection uses -1 (and rulesets omit the field) for "any".
    """
    return value if isinstance(value, int) and value > 0 else None


async def _ruleset_checks(
    client: GitHubClient, owner: str, repo: str, branch: str
) -> set[RequiredCheck]:
    """Required status checks from the rulesets active on a branch."""
    required: set[RequiredCheck] = set()
    rules = await _read_all(client, f"/repos/{owner}/{repo}/rules/branches/{branch}", None)
    for rule in rules:
        if rule.get("type") != "required_status_checks":
            continue
        for check in (rule.get("parameters") or {}).get("required_status_checks") or []:
            context = check.get("context")
            if isinstance(context, str) and context:
                required.add((context, _app_id(check.get("integration_id"))))
    return required


async def _classic_checks(
    client: GitHubClient, owner: str, repo: str, base: str
) -> set[RequiredCheck]:
    """Required status checks from a branch's classic protection.

    Read from the branch itself, which shows its protection to any token
    that can read the repository; the protection endpoint needs
    Administration: read, which a merging token should not hold. Any error,
    or a protected branch whose protection is not shown, refuses the merge:
    the gate cannot tell "no required checks" from "checks it was not shown".
    """
    branch = quote(base, safe="")
    try:
        info = await client.get(f"/repos/{owner}/{repo}/branches/{branch}")
    except (GitHubApiError, NotFoundError, PermissionDeniedError, RateLimitError) as e:
        raise MergeRefusedError(
            f"Refusing to merge: cannot read the branch protection of {base!r} ({e})"
        ) from e
    if not info.get("protected"):
        return set()
    protection = info.get("protection")
    if not isinstance(protection, dict):
        raise MergeRefusedError(
            f"Refusing to merge: branch {base!r} is protected but its protection is not shown"
        )
    classic = protection.get("required_status_checks") or {}

    # "checks" carries the app each context must come from; older protection
    # has only "contexts".
    pairs = [(c.get("context"), _app_id(c.get("app_id"))) for c in classic.get("checks") or []]
    if not pairs:
        pairs = [(context, None) for context in classic.get("contexts") or []]
    return {(context, app) for context, app in pairs if isinstance(context, str) and context}


async def _required_checks(
    client: GitHubClient, owner: str, repo: str, base: str
) -> set[RequiredCheck]:
    """Every status check the base branch requires, from rulesets and classic
    branch protection."""
    rulesets = await _ruleset_checks(client, owner, repo, quote(base, safe=""))
    return rulesets | await _classic_checks(client, owner, repo, base)


def _judge_run(run: dict[str, Any]) -> str | None:
    """Why a check run does not satisfy a required check, or None if it does."""
    if run.get("status") != "completed":
        return f"pending (check run {run.get('status')})"
    conclusion = run.get("conclusion")
    if conclusion not in PASSING_CONCLUSIONS:
        return f"failed (check run concluded {conclusion})"
    return None


def _index_runs(
    check_runs: list[dict[str, Any]], any_app: bool = True
) -> dict[RequiredCheck, dict[str, Any]]:
    """The most recent (highest id) check run per (name, app id) and, when
    ``any_app``, per (name, None) for checks any app may report.

    Without ``any_app`` (the runs are only the Actions jobs, so another app's
    run of the same name may be unseen) a check any app may report is judged
    by its commit status alone, or is missing.
    """
    index: dict[RequiredCheck, dict[str, Any]] = {}
    for run in sorted(check_runs, key=lambda r: r.get("id") or 0):
        name = run.get("name")
        if not isinstance(name, str):
            continue
        app_id = (run.get("app") or {}).get("id")
        if any_app:
            index[(name, None)] = run
        if isinstance(app_id, int):
            index[(name, app_id)] = run
    return index


def _judge_check(
    check: RequiredCheck,
    runs: dict[RequiredCheck, dict[str, Any]],
    statuses: dict[str, dict[str, Any]],
) -> str | None:
    """Why a required check is not satisfied, or None if it is.

    A check run named after the context decides; if several share the name,
    the most recent (highest id) does. When the rule names an app, only that
    app's runs count and a commit status cannot stand in. Otherwise, with no
    such run, the commit status of that context decides.
    """
    context, app_id = check
    run = runs.get(check)
    if run is not None:
        return _judge_run(run)

    status = statuses.get(context) if app_id is None else None
    if status is None:
        source = f" from app {app_id}" if app_id is not None else ""
        return f"missing (no check run{source} or status on the head commit)"
    match status.get("state"):
        case "success":
            return None
        case "pending":
            return "pending (status pending)"
        case state:
            return f"failed (status {state})"


async def _gate_problems(
    client: GitHubClient,
    owner: str,
    repo: str,
    head_sha: str,
    required: set[RequiredCheck],
) -> tuple[list[str], str]:
    """One line per required check that the head commit does not satisfy,
    and where the check runs were read from."""
    try:
        check_runs, source = await _head_check_runs(client, owner, repo, head_sha, _refuse_cut)
    except API_ERRORS as e:
        raise MergeRefusedError(
            f"Refusing to merge: could not read the check runs of {head_sha}: {e}"
        ) from e
    raw_statuses = await _read_all(
        client, f"/repos/{owner}/{repo}/commits/{head_sha}/status", "statuses"
    )
    # The combined status lists the latest status per context, but its order
    # is not relied on: where a context repeats, the newest (highest id) wins.
    statuses: dict[str, dict[str, Any]] = {}
    for status in sorted(raw_statuses, key=lambda s: s.get("id") or 0):
        if isinstance(status.get("context"), str):
            statuses[status["context"]] = status

    runs = _index_runs(check_runs, any_app=source == SOURCE_CHECK_RUNS)
    problems = []
    for check in sorted(required, key=lambda c: (c[0], c[1] or 0)):
        reason = _judge_check(check, runs, statuses)
        if reason:
            problems.append(f"{check[0]}: {reason}")
    return problems, source


async def _head_and_base(
    client: GitHubClient, owner: str, repo: str, pull_number: int
) -> tuple[str, str]:
    """The PR's current head SHA (lower case) and base branch."""
    pr = await client.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")
    head_sha = validate_commit_sha((pr.get("head") or {}).get("sha"), "head sha")
    base = (pr.get("base") or {}).get("ref")
    if not head_sha or not isinstance(base, str) or not base:
        raise MergeRefusedError("Refusing to merge: could not resolve the PR head and base")
    return head_sha, validate_ref(base, "base")


async def merge_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
    merge_method: str = "merge",
    sha: str | None = None,
    allow_no_required_checks: bool = False,
) -> dict[str, Any]:
    """Merge a pull request, only once its required checks are green.

    The tool enforces the base branch's required status checks itself,
    before asking GitHub to merge. GitHub lets an organization owner, or an
    actor on a ruleset's bypass list, merge past failing required checks;
    with such a token GitHub would merge a red PR, so the check cannot be
    left to GitHub.

    1. Read the PR's base branch and current head SHA. If ``sha`` is given
       and is not the head, refuse.
    2. Collect the required checks of the base branch from its rulesets and
       its classic branch protection. If the protection cannot be read
       (other than a 404, which means none), refuse.
    3. With no required checks, refuse unless ``allow_no_required_checks``.
    4. Each required check must have, on the head commit, a completed check
       run concluding success, skipped or neutral (the most recent run of
       that name), or a commit status of success. Otherwise refuse, listing
       each check and why.
    5. Re-read the PR and refuse if its head or base changed meanwhile, then
       merge with the head SHA pinned, so a later push makes GitHub refuse
       the merge (409) rather than merge unchecked code.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        merge_method: "merge", "squash", or "rebase"
        sha: Full commit SHA the PR head must still be at (optional)
        allow_no_required_checks: Merge even if the base branch requires no
            checks (default False: refuse)

    Returns:
        Merge result (merged, sha of the merge commit, message), the
        ``head_sha`` that was checked and merged, and ``required_checks``

    Raises:
        MergeRefusedError: If the gate refuses the merge
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")
    if merge_method not in MERGE_METHODS:
        allowed = ", ".join(sorted(MERGE_METHODS))
        raise ValidationError(f"Invalid merge_method. Allowed: {allowed}")
    expected_head = validate_commit_sha(sha)

    client = get_client()
    head_sha, base = await _head_and_base(client, owner, repo, pull_number)
    if expected_head and expected_head != head_sha:
        raise MergeRefusedError(
            f"Refusing to merge: the PR head is {head_sha}, not the expected {expected_head}"
        )

    required = await _required_checks(client, owner, repo, base)
    if not required and not allow_no_required_checks:
        raise MergeRefusedError(
            f"Refusing to merge: branch {base!r} requires no status checks. "
            "Pass allow_no_required_checks=True to merge without any."
        )
    source: str | None = None
    if required:
        problems, source = await _gate_problems(client, owner, repo, head_sha, required)
        if problems:
            via = (
                " (check runs read from the Actions API; this token cannot read check-runs)"
                if source == SOURCE_ACTIONS
                else ""
            )
            raise MergeRefusedError(
                f"Refusing to merge: required checks are not green on {head_sha}{via}: "
                + "; ".join(problems)
            )

    # The merge request pins the head but not the base. Re-read the PR so a
    # retarget, or a push, during the gate is refused rather than merged into
    # a branch whose checks were not the ones judged.
    if await _head_and_base(client, owner, repo, pull_number) != (head_sha, base):
        raise MergeRefusedError(
            "Refusing to merge: the PR head or base changed while its checks were read"
        )

    result = await client.put(
        f"/repos/{owner}/{repo}/pulls/{pull_number}/merge",
        json_data={"merge_method": merge_method, "sha": head_sha},
    )
    return {
        "merged": result.get("merged"),
        "sha": result.get("sha"),
        "message": result.get("message"),
        "head_sha": head_sha,
        "required_checks": sorted({context for context, _ in required}),
        "checks_source": source,
    }


async def _collect_pages(client: GitHubClient, path: str) -> tuple[list[dict[str, Any]], bool]:
    """Read a paginated list up to MAX_PR_COMMENTS_PER_KIND items.

    Returns the items and whether GitHub had more than were read.
    """
    collected: list[dict[str, Any]] = []
    has_more = False
    for page in range(1, MAX_PR_COMMENTS_PER_KIND // MAX_PER_PAGE + 1):
        result = await client.get(path, params={"per_page": MAX_PER_PAGE, "page": page})
        collected.extend(result.get("items", []))
        has_more = "next_page" in result.get("pagination", {})
        if not has_more:
            break
    cut = has_more or len(collected) > MAX_PR_COMMENTS_PER_KIND
    return collected[:MAX_PR_COMMENTS_PER_KIND], cut


def _discussion_item(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce an issue comment, review comment, or review to common fields.

    A review has no created_at; its submitted_at takes that place.
    """
    item: dict[str, Any] = {
        "kind": kind,
        "id": raw.get("id"),
        "author": (raw.get("user") or {}).get("login"),
        "created_at": raw.get("created_at") or raw.get("submitted_at"),
        "body": raw.get("body") or "",
        "html_url": raw.get("html_url"),
    }
    if kind == "review_comment":
        item["path"] = raw.get("path")
        item["line"] = raw.get("line")
        item["in_reply_to_id"] = raw.get("in_reply_to_id")
        item["review_id"] = raw.get("pull_request_review_id")
    if kind == "review":
        item["state"] = raw.get("state")
    return item


async def list_pull_request_comments(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """List everything said on a pull request, in one chronological list.

    Combines three GitHub collections, tagging each item with its ``kind``:

    - ``issue_comment``: comments in the PR conversation
    - ``review_comment``: comments on the diff, with path, line, the review
      they belong to and, for a reply, the ``in_reply_to_id`` of the comment
      they answer
    - ``review``: submitted reviews, with their state (APPROVED,
      CHANGES_REQUESTED, COMMENTED, ...)

    Every item carries id, author (login), created_at, body and html_url.
    Each collection is read oldest first and capped; a kind named in
    ``truncated_kinds`` had newer items that are not in the result.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        {"pull_number", "total_count", "truncated", "truncated_kinds", "items"}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    sources = {
        "issue_comment": f"/repos/{owner}/{repo}/issues/{pull_number}/comments",
        "review_comment": f"/repos/{owner}/{repo}/pulls/{pull_number}/comments",
        "review": f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
    }

    items: list[dict[str, Any]] = []
    truncated_kinds: list[str] = []
    for kind, path in sources.items():
        try:
            raw_items, cut = await _collect_pages(client, path)
        except (GitHubApiError, NotFoundError):
            # GitHub answers /pulls/{n}/... for a plain issue with a 403 that
            # reads like a token scope problem. Say what is actually wrong.
            if kind != "issue_comment":
                issue = await client.get(f"/repos/{owner}/{repo}/issues/{pull_number}")
                if "pull_request" not in issue:
                    raise ValidationError(
                        f"#{pull_number} is an issue, not a pull request; "
                        "use list_issue_comments_tool"
                    ) from None
            raise
        items.extend(_discussion_item(kind, raw) for raw in raw_items)
        if cut:
            truncated_kinds.append(kind)

    items.sort(key=lambda item: item["created_at"] or "")

    return {
        "pull_number": pull_number,
        "total_count": len(items),
        "truncated": bool(truncated_kinds),
        "truncated_kinds": truncated_kinds,
        "items": items,
    }


async def reply_to_review_comment(
    owner: str | None,
    repo: str,
    pull_number: int,
    comment_id: int,
    body: str,
) -> dict[str, Any]:
    """Reply in the thread of a pull request review comment.

    ``comment_id`` must be a top-level review comment (one whose
    ``in_reply_to_id`` is empty); GitHub rejects a reply to a reply.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        comment_id: ID of the review comment to reply to
        body: Reply body (Markdown)

    Returns:
        Created reply details (id, html_url, in_reply_to_id)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")
    comment_id = validate_positive_int(comment_id, "comment_id")
    # A reply is a comment: same body limits as an issue comment.
    validated = CreateIssueCommentInput(body=body)

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies",
        json_data={"body": validated.body},
    )
    return {
        "id": result.get("id"),
        "html_url": result.get("html_url"),
        "in_reply_to_id": result.get("in_reply_to_id"),
    }
