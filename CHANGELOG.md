# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.1.1] - 2026-11-10

### Fixed

- The container installed its dependencies by resolving `pyproject.toml`
  fresh instead of from the committed, Dependabot-maintained `uv.lock`.
  `pip install .` reads only the floor pins, so the image could ship whatever
  had been released that morning -- a dependency set no test had ever run
  against. That is how `google-genai` 3.0 reached `mcp-gemini`'s production
  with CI green (RT #1564); this repo had the same gap. The builder now
  installs from a `uv export` of the lock with `--no-deps`, so the image
  carries exactly what CI tested.

## [2.1.0] - 2026-11-09

### Fixed

- **The JSON path had no ceiling.** The response size limit read the
  `content-length` header and nothing else, so a reply without that header was
  read whole into memory. The job-log download has always read in bounded
  pieces, which is what made the gap easy to miss: the repo looked like it
  streamed because one of its two read paths did. The JSON path now reads in
  bounded pieces too, measured before each chunk is copied in.

- **An error that is not GitHub's JSON shape says what it was.** It arrived as
  `Unknown error` or 200 bare characters of body with no indication of where
  they came from, so an Enterprise login page, a proxy error and the API
  refusing something were one message. Such a body is now quoted, bounded,
  alongside the method, URL, status and content-type of the request it
  answered. GitHub's own `message` is still used verbatim when present, now
  length-bounded.

- **The URL in an error carries no secret.** Userinfo is dropped, and
  `access_token` — GitHub's own retired query-string auth — along with
  `client_secret`, `code` and `token` are redacted by name. By name rather
  than by dropping the query string, because `per_page`, `state` and `sha` are
  the diagnosis.

### Added

- **The client says what it is.** Requests carry
  `User-Agent: mcp-github-crunchtools/<version> (+<repo url>)`, with the
  version read from installed package metadata. GitHub asks API clients to
  send one, and httpx's default `python-httpx/<version>` is what bot
  protection answers with a challenge page (RT #1596).

### Changed

- Client tests drive `build_request` and `send` rather than `request`, because
  the client now streams. The contract tests in
  `tests/test_http_contract.py` use the existing `_patch_transport`, which
  gives them a real `httpx.AsyncClient`: the agent string and the bounded read
  are the client's own behaviour, so a mock standing in for it cannot see them.

- Inherits constitution v1.36.0, whose MCP Server profile 1.8.0 states the
  outbound HTTP contract (RT #1601).

## [2.0.1] - 2026-10-31

### Security

- Upgraded locked dependencies within their declared ranges to clear the
  advisories the fleet dependency audit found (anyio, authlib, cryptography, dnspython, joserfc, opentelemetry-api, pydantic-settings, pyjwt).

## [2.0.0] - 2026-10-30

### Changed

- **Breaking:** `get_failed_job_logs_tool` no longer returns the raw log tail
  (`log`/`log_lines`) by default. Each failed job now carries a
  `failure_summary` instead — the tail lines that name the cause (error
  annotations, test failures, tracebacks, non-zero exits), with
  `summary_lines`. A failed job's log can run to the byte cap and, for a
  repository whose CI quotes attack corpora (e.g. a prompt-injection defense
  project), a scanning gateway may flag and withhold the whole tail, leaving
  the operator unable to see why CI failed. The distilled summary is small and
  signal-only, so it is far more likely to pass such a gateway. Pass
  `include_raw_log=true` to also get the full cleaned tail as `log`/`log_lines`,
  exactly as before (that path is what a gateway may still withhold). The
  summary counts against the same 256 KiB result budget as the raw tail.

### Added

- `get_failed_job_logs_tool` gains an `include_raw_log` parameter (default
  `false`).

## [1.6.0] - 2026-10-20

### Changed

- Container base images pinned to `quay.io/hummingbird/python:3.14*` instead of
  `latest`, which moved to Python 3.15.0 on 2026-10-20 (crunchtools/constitution#66).

## [1.5.0] - 2026-10-20

### Added

- `merge_pull_request_tool` and `get_pull_request_checks_tool` work with a
  fine-grained token. GitHub cannot grant one the Checks permission, so
  check-runs answers 403; the tools then read the head commit's Actions jobs
  (Actions: read), each of which is a check run with the same id and name.
  Only Actions-reported checks are visible that way, so the merge gate
  refuses a required check that names another app, or that accepts any app
  and has no commit status. Both results carry `checks_source`.

### Fixed

- `get_pull_request_checks_tool` reads every page of check runs, not just the
  first, up to the merge gate's page limit; past it the verdict says
  `truncated` and is not `ready_to_merge`.

## [1.4.0] - 2026-10-17

### Added

- `list_issue_comments_tool`: the comments on an issue or a pull request
  conversation, oldest first, one page at a time, with id, author,
  author_association, created_at, updated_at, body and html_url (#45).

### Fixed

- `list_pull_request_comments_tool` called on a plain issue returned GitHub's
  403 "Resource not accessible by personal access token", which reads like a
  token scope problem. It now says the number is an issue and points to
  `list_issue_comments_tool` (#45).

## [1.3.2] - 2026-10-17

### Fixed

- The integer ID parameters of the read tools (`issue_number`, `pull_number`,
  `run_id`) now publish `minimum: 1` in their schema, so `0` and negative IDs
  are rejected.

## [1.3.1] - 2026-10-16

### Fixed

- A primary rate limit reported GitHub's `x-ratelimit-reset` epoch as the
  wait ("Retry after 1792152901 seconds"). It now reports the seconds left
  until the reset.

## [1.3.0] - 2026-10-14

### Added

- `GITHUB_ACCEPT_REQUEST_TOKEN` (default off): over HTTP, act with the token
  in each request's `Authorization: Bearer <token>` header, the way GitHub's
  hosted MCP server takes it, falling back to `GITHUB_TOKEN`. With it on,
  `GITHUB_TOKEN` is optional. A malformed header is refused, never
  forwarded; a call with no token at all fails before reaching GitHub.
  stdio is unchanged.
- `merge_pull_request_tool` takes `allow_no_required_checks` (default
  False).

### Changed

- `merge_pull_request_tool` enforces the base branch's required status
  checks itself before merging: from rulesets and classic branch
  protection, every required check must have a passing check run (success,
  skipped or neutral) or a successful status on the head commit, or the
  merge is refused with each offending check named. A branch with no
  required checks is refused unless `allow_no_required_checks=True`, and a
  branch protection that cannot be read is refused. Classic protection is
  read from the branch itself, so no Administration permission is needed.
  The merge is always pinned to the checked head SHA. It now needs Pull
  requests: read and Commit statuses: read as well as Contents: write.

### Security

- An organization owner's token can bypass required checks on GitHub's
  side; the merge gate closes that for this tool.
- The request token is scrubbed from error messages like `GITHUB_TOKEN`,
  and is passed per call, never stored on the shared HTTP client.

## [1.2.0] - 2026-10-12

### Added

- `create_pull_request_tool`: open a pull request, optionally as a draft; the
  head may be `owner:branch` for a fork.
- `merge_pull_request_tool`: merge, squash or rebase a pull request. `sha` is
  the expected head commit; GitHub refuses the merge if the branch has moved.
- `list_pull_request_comments_tool`: conversation comments, diff comments and
  reviews in one chronological list, each tagged with its kind, author and id.
  Each kind is capped at 300 items and the result says when one was cut.
- `reply_to_review_comment_tool`: reply in the thread of a diff comment.
- `get_workflow_run_tool`: one run's status, conclusion, head SHA and branch,
  event and jobs, without logs.
- `get_failed_job_logs_tool`: the last lines of the log of each failed job in
  a run, with ANSI escapes and timestamps removed. Bounded to 1000 lines per
  job, 5 jobs and 256 KiB per result; the result says when something was cut.
- `create_release_tool`: create a release and, if needed, its tag.
- README and SECURITY.md list the fine-grained token permission each tool
  needs.

### Security

- The API client is created with `follow_redirects=False`. GitHub redirects a
  job log to a pre-signed storage URL; that URL is fetched by a separate
  client that has no token, over HTTPS only, and is never logged or put in an
  error message.

### Changed

- README lists all 25 tools; it had stopped at the first eleven.

## [1.1.0] - 2026-10-10

### Added

- The eleven tools that only read (`list_issues`, `get_issue`,
  `list_pull_requests`, `get_pull_request`, `get_pull_request_diff`,
  `get_pull_request_checks`, `get_file_content`, `list_repo_tree`,
  `search_code`, `search_issues`, `list_workflow_runs`) publish
  `readOnlyHint: true`. A gateway uses it to decide whether an invalid optional
  argument may be dropped or must refuse the call (crunchtools/constitution#35).
- Tests pin every registered tool into `READ_ONLY` or `WRITES`, and check that
  each read-only tool sends GitHub nothing but GET requests.

### Changed

- Inherits constitution v1.22.0; the workflow pins and the pre-commit hook rev
  move with it.

### Fixed

- `server.json` said 0.1.0 and the Containerfile label said 0.3.0; both carry
  the release version again.

## [1.0.1] - 2026-10-02

### Fixed

- The package, `__version__` and the MCP server reported 0.4.0 while the
  v1.0.0 release and image said 1.0.0; all three now carry the release version.

### Changed

- Constitution is now a v1.18.0 manifest: it holds only what is specific to
  this repo; fleet and profile rules apply by reference.
- Constitution validation is pinned to the inherited release via
  `.github/workflows/constitution.yml`.
- Dependabot auto-merges GitHub Actions minor and patch updates.

## [1.0.0] - 2026-09-20

First tagged release. This image has been running in production since before
it had version control. No changes are recorded prior to this point --
RT #1484 added this file on 2026-09-19, before this repo's first tag.
