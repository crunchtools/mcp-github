# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
