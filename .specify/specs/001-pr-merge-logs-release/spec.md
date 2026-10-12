# Specification: Pull Request, Run Log and Release Tools

> **Spec ID:** 001-pr-merge-logs-release
> **Status:** Implemented
> **Version:** 1.2.0
> **Author:** crunchtools.com
> **Date:** 2026-10-12

## Overview

An agent that takes a change from a branch to a release needs to open the pull
request, read what reviewers and CI said about it, answer them, merge, and
publish. Until now it did the missing steps with the `gh` CLI, which hands it
other people's text with no gateway in between. These seven tools close that
gap so the whole loop runs through the MCP server.

---

## New Tools

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `create_pull_request_tool` | POST | `/repos/{owner}/{repo}/pulls` | Open a pull request (write) |
| `merge_pull_request_tool` | PUT | `/repos/{owner}/{repo}/pulls/{pull_number}/merge` | Merge, squash or rebase; optional expected head SHA (write) |
| `list_pull_request_comments_tool` | GET | `.../issues/{n}/comments` + `.../pulls/{n}/comments` + `.../pulls/{n}/reviews` | One list of everything said on a PR |
| `reply_to_review_comment_tool` | POST | `/repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies` | Reply in a review thread (write) |
| `get_workflow_run_tool` | GET | `/repos/{owner}/{repo}/actions/runs/{run_id}` + `.../jobs` | Run status and jobs, no logs |
| `get_failed_job_logs_tool` | GET | `.../actions/runs/{run_id}/jobs` + `.../actions/jobs/{job_id}/logs` | Tail of each failed job's log |
| `create_release_tool` | POST | `/repos/{owner}/{repo}/releases` | Create a release and its tag (write) |

The three GET tools publish `readOnlyHint`. Not in scope: creating or forking
repositories, deleting packages, further search tools.

### Result shapes and caps

| Tool | Cap | How the result reports it |
|------|-----|---------------------------|
| `list_pull_request_comments_tool` | 300 items per kind, read oldest first (at most 9 requests) | `truncated`, `truncated_kinds` |
| `get_workflow_run_tool` | 300 jobs | `jobs_truncated` |
| `get_failed_job_logs_tool` | `tail_lines` at most 1000 (default 200); 5 failed jobs; 256 KiB of log text per result, split evenly between jobs; 20 MB per download | `tail_lines` (value used), `failed_jobs_omitted`, per-job and overall `truncated` |

A job is failed when its conclusion is `failure` or `timed_out`. Cancelled
jobs are left out: in a failed run they are mostly siblings stopped by
fail-fast, and their logs say nothing about the cause.

---

## Security Considerations

### Layer 1 — Token Protection

- GitHub serves a job log as a 302 to a pre-signed URL on a storage host. The
  API client is created with `follow_redirects=False`; the redirect target is
  fetched by a second client that has no default headers, so the token is not
  sent there.
- The signed URL is a short-lived credential. It is not logged, not put in an
  error message, and not kept in an exception chain.

### Layer 2 — Input Validation

- `MERGE_METHODS` allowlist; `validate_commit_sha` for the expected head;
  `validate_head` for `branch` or `owner:branch`; `validate_ref` for base,
  tag and target.
- `CreateReleaseInput` for the release title and notes. Pull request title
  and body reuse `CreateIssueInput`, and a review reply reuses
  `CreateIssueCommentInput`: the limits are the same.
- Blank optional values (`sha`, `target_commitish`, `name`) mean "not given".

### Layer 3 — API Hardening

- The redirect target must be HTTPS, name a host rather than an IP address,
  and carry no embedded credentials. It is not redirected further and must
  answer 200. The host is not held to a list of names: GitHub documents no
  stable set of log-storage hosts, and GHES storage is the operator's.
- The download is streamed with a rolling 256 KiB tail and abandoned past
  20 MB. Paging loops are bounded by a page count, not by what the server
  says.

### Layer 4 — Dangerous Operation Prevention

- No filesystem, shell or code evaluation. Logs are held in memory only.
- Comments, reviews and logs are text written by others. The server returns
  them as data and bounds their size; it does not interpret them.

---

## Module Changes

### New Files

| File | Purpose |
|------|---------|
| `tools/releases.py` | `create_release` |

### Modified Files

| File | Changes |
|------|---------|
| `client.py` | `_send` split out of `_request`; `get_redirected_tail`; `follow_redirects=False` |
| `models.py` | `MERGE_METHODS`, `validate_head`, `validate_commit_sha`, `CreateReleaseInput` |
| `tools/pull_requests.py` | `create_pull_request`, `merge_pull_request`, `list_pull_request_comments`, `reply_to_review_comment` |
| `tools/actions.py` | `get_workflow_run`, `get_failed_job_logs` |
| `tools/__init__.py` | Exports |
| `server.py` | Seven `@mcp.tool` wrappers |

---

## Testing Requirements

### Mocked API Tests

- [x] Happy path, validation refusal and GitHub error path for each tool
- [x] Caps: comments per kind, jobs per run, `tail_lines`, bytes, failed jobs
- [x] The storage request carries no `Authorization` header (real httpx
      client over a mock transport, so the assertion is on the request as sent)
- [x] Redirects that are not HTTPS, carry credentials or address an IP are
      refused; storage errors and transport failures do not expose the
      signed URL

### Input Validation Tests

- [x] `validate_head`, `validate_commit_sha`, `CreateReleaseInput`

### Tool Count Update

- [x] `test_tool_count` is 25; `READ_ONLY` and `WRITES` updated

---

## Dependencies

- Depends on: 000-baseline
- Blocks: none

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2026-10-12 | Implemented |
