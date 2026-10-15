# Security Design Document

This document describes the security architecture of mcp-github-crunchtools.

## 1. Threat Model

### 1.1 Assets to Protect

| Asset | Sensitivity | Impact if Compromised |
|-------|-------------|----------------------|
| GitHub Personal Access Token | Critical | Full account access, code access, CI/CD manipulation |
| Repository Source Code | High | Intellectual property theft, supply chain attacks |
| Default Branch and Releases | High | A merge or a published release ships code to users |
| Pull Requests / Issues | Medium | Information disclosure, workflow manipulation |
| CI Check Results and Job Logs | Medium | Infrastructure details; a log can echo a secret a job printed |

### 1.2 Threat Actors

| Actor | Capability | Motivation |
|-------|------------|------------|
| Malicious AI Agent | Can craft tool inputs | Data exfiltration, privilege escalation |
| Local Attacker | Access to filesystem | Token theft, configuration tampering |
| Network Attacker | Man-in-the-middle | Token interception (mitigated by TLS) |

### 1.3 Attack Vectors

| Vector | Description | Mitigation |
|--------|-------------|------------|
| **Token Leakage** | Token exposed in logs, errors, or outputs | Never log tokens; scrub the env and request tokens from errors |
| **Token Mix-up** | One HTTP caller's token used for another's request | Per-call header and a request-scoped context variable; nothing on the shared client (2.2) |
| **Check Bypass** | A token allowed to bypass rulesets merges a PR with failing checks | The merge tool enforces required checks itself (2.7) |
| **Input Injection** | Malicious owner/repo or path | Strict input validation |
| **Path Traversal** | Manipulated file paths | Allowlist validation, reject `..` |
| **SSRF** | Redirect API calls to internal services | HTTPS enforcement, URL validation |
| **Token Forwarding** | A redirect carries the token to another host | The API client follows no redirects; the job-log redirect is fetched by a client with no token (2.6) |
| **Untrusted Text** | Comments, reviews and job logs are written by other people and by the code under test | Returned as data with bounded size; the caller (or a gateway in front of it) must not treat them as instructions |
| **Unintended Merge** | The PR head moves between the check and the merge | `merge_pull_request_tool` always pins the merge to the head it checked; GitHub refuses (409) if it moved |
| **Denial of Service** | Exhaust GitHub rate limits | Rate-limit awareness |
| **Privilege Escalation** | Access beyond token scope | Server relies on token scope |
| **Supply Chain** | Compromised dependencies | Automated CVE scanning |

## 2. Security Architecture

### 2.1 Defense in Depth Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Input Validation                                    │
│ - Allowlist for owner/repo characters                        │
│ - Positive-integer validation for issue/PR numbers           │
│ - Path traversal rejection for file reads                    │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: Token Handling                                      │
│ - Environment variable only (never file, never arg)          │
│ - Never log, never include in errors                         │
│ - Use Authorization: Bearer header (not in URL)              │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: API Client Hardening                                │
│ - Configurable base URL with HTTPS enforcement (GHES)        │
│ - Pinned X-GitHub-Api-Version                                 │
│ - TLS certificate validation (default in httpx)              │
│ - Request timeout enforcement (30s)                          │
│ - Response size limits (10MB)                                │
├─────────────────────────────────────────────────────────────┤
│ Layer 4: Output Sanitization                                 │
│ - Redact tokens from any error messages                      │
│ - Limit response sizes to prevent memory exhaustion          │
│ - Structured errors without internal details                 │
├─────────────────────────────────────────────────────────────┤
│ Layer 5: Runtime Protection                                  │
│ - No filesystem writes                                       │
│ - No shell execution (subprocess)                            │
│ - No dynamic code evaluation (eval/exec)                     │
├─────────────────────────────────────────────────────────────┤
│ Layer 6: Supply Chain Security                               │
│ - Automated CVE scanning via GitHub Actions                  │
│ - Dependabot alerts enabled                                  │
│ - Container built on Hummingbird for minimal CVEs            │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Token Security

`GITHUB_TOKEN` is read from the environment only and held as a pydantic
`SecretStr`; `Config.__repr__()` and `__str__()` print `token=***`. It is
required unless `GITHUB_ACCEPT_REQUEST_TOKEN` is on.

#### Per-request token

With `GITHUB_ACCEPT_REQUEST_TOKEN` set to `true`, `1` or `yes`, the server
takes the caller's token from each HTTP request's `Authorization` header, as
GitHub's own hosted MCP server does. Off (the default), the header is
ignored and nothing changes.

- The token is chosen per API call. An incoming `Authorization: Bearer
  <token>` is sent as that call's own header, overriding the shared client's
  default; without one, `GITHUB_TOKEN` is used; with neither, the call fails
  before any request is made. The shared httpx client carries an
  `Authorization` default only when `GITHUB_TOKEN` is set, and never a
  request's token, so concurrent requests with different tokens each send
  their own. A test runs five requests in flight at once to show it.
- The header must match `Bearer <token>` exactly: the scheme in any case, a
  single space, then 1 to 1024 printable non-space ASCII characters. Anything
  else (another scheme, spaces, control characters, an empty value) is
  refused with an error that does not echo it, and is never forwarded. A
  malformed header does not fall back to `GITHUB_TOKEN`.
- FastMCP strips `Authorization` from the headers it exposes; the client asks
  for it explicitly, and only when the option is on. stdio has no request
  headers and always uses `GITHUB_TOKEN`.
- The request token is kept in a context variable for the duration of the
  request so that error messages scrub it (2.5).

Turning the option on makes the server act as whoever presents a token. That
grants no access the caller did not already have, but the HTTP port should
still be reachable only by intended callers, over TLS, since the token
crosses it.

### 2.3 URL Security

The API base URL is validated to prevent SSRF:

- Must be a valid URL with scheme and netloc
- Must use HTTPS unless connecting to localhost
- Trailing slashes are stripped
- Defaults to `https://api.github.com`; override with `GITHUB_API_URL` for GHES

### 2.4 Input Validation Rules

All inputs are validated:

- **Owner / repo names**: letters, digits, dots, hyphens, underscores only
- **Issue / PR / page numbers**: must be positive integers
- **File paths**: rejected if they contain `..`
- **States**: allowlist of "open", "closed", "all"
- **Merge methods**: allowlist of "merge", "squash", "rebase"
- **Git refs** (PR base, release tag and target): git check-ref-format rules;
  a PR head may also be `owner:branch` for a fork
- **Expected head SHA**: a full 40 or 64 character hex commit SHA
- **Comment bodies**: 1-65536 characters, extra fields rejected (extra="forbid")
- **Titles and bodies** (issues, PRs, releases): at most 256 and 65536 characters

### 2.5 Error Handling

Errors are sanitized before being returned:

```python
def scrub_tokens(message: str) -> str:
    for token in (os.environ.get("GITHUB_TOKEN", ""), request_token.get()):
        if token:
            message = message.replace(token, "***")
    return message
```

`GitHubApiError` passes every message through `scrub_tokens`, which removes
both `GITHUB_TOKEN` and the token of the current request.

GitHub signals primary rate limiting with HTTP 403 plus
`x-ratelimit-remaining: 0`; the client maps this (and HTTP 429) to a
`RateLimitError` that surfaces the retry window.

### 2.6 Job-Log Redirects

`get_failed_job_logs_tool` is the only tool whose data comes from a host other
than the API. GitHub answers `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs`
with a 302 to a short-lived, pre-signed URL on a storage host.

- The API client is built with `follow_redirects=False`, so the client that
  holds the token never follows a redirect on its own.
- The redirect target is fetched by a separate client created with no default
  headers. No `Authorization` header reaches the storage host; a test asserts
  this on the request as sent.
- The target must be `https`, name a host rather than an IP address (in any
  spelling, including `2130706433` and `0x7f.0.0.1`), and carry no embedded
  credentials. It is not redirected further, and anything
  but a 200 is an error.
- The target host is not checked against a list of names. GitHub documents no
  stable set of log-storage hosts and a GitHub Enterprise Server uses its
  operator's storage, so a list would break the tool. The `Location` comes
  from the configured API over verified TLS and no tool argument reaches it;
  whoever could forge it already receives the token on every API request.
- The signed URL is never logged and never placed in an error message, and a
  storage error body is not echoed.
- The download is streamed. Only the last 256 KiB are held in memory and the
  download is abandoned past 20 MB.

Log text is then reduced before it is returned: ANSI escapes and per-line
timestamps are removed, each job is cut to its last `tail_lines` lines (at
most 1000), logs are returned for at most 5 failed jobs, and all log text in
one result stays within 256 KiB. The result says when any of these cut
something.

### 2.7 Merge Gate

`merge_pull_request_tool` enforces the base branch's required status checks
itself. GitHub lets an organization owner, or an actor on a ruleset's bypass
list, merge past failing required checks, so a token with that standing
would otherwise merge a red pull request.

- The PR's head SHA and base are read first; a caller's `sha` that is not
  the head is refused.
- Required checks come from the branch's active rulesets
  (`GET /repos/{owner}/{repo}/rules/branches/{branch}`) and its classic
  protection, as shown on the branch (`GET .../branches/{branch}`), which
  needs no Administration permission. An error reading either, or a
  protected branch whose protection is not shown, refuses the merge: the
  gate cannot tell that from there being no checks.
- No required checks at all refuses the merge unless the caller passes
  `allow_no_required_checks=True`.
- Each required check needs, on the head commit, a completed check run of
  that name concluding `success`, `skipped` or `neutral` (the most recent run
  of the name, by id, decides) or a commit status of `success`. A rule that
  names an app (`integration_id`, or `app_id` in classic protection) is
  satisfied only by that app's check runs, never by a commit status, which
  anyone with Commit statuses: write could post.
- Every list is read in full, up to 10 pages of 100; a longer list refuses
  the merge rather than be judged in part.
- Just before merging the PR is read again, and a changed head or base
  refuses the merge: the merge call pins the head but not the base, so a
  retarget during the gate would otherwise land on a branch whose checks
  were not judged. The merge request pins `sha` to the checked head, so a
  push after that re-read makes GitHub answer 409. A retarget in the
  milliseconds between the re-read and the merge call remains possible;
  GitHub offers no way to pin the base.
- Other branch rules, such as required reviews, are not re-enforced; a token
  that may bypass them still does.

## 3. Minimum Permission Scopes

Permissions below are the repository permissions of a fine-grained personal
access token. Metadata: read comes with any of them.

### 3.1 Read-Only Token (Safest)

Grant **read** on **Contents**, **Issues**, **Pull requests** and **Actions**
(plus **Commit statuses** for `get_pull_request_checks_tool`),
or `repo:status` + `public_repo` for classic tokens limited to public
repositories.

**Capabilities:** list/read issues, PRs, diffs, checks, PR comments and
reviews, workflow runs, failed-job logs, files; search
**Risk:** Information disclosure only. Job logs can contain whatever a job
printed.

### 3.2 Standard Token

Add **write** on **Issues** and **Pull requests**.

**Capabilities:** the above plus opening and updating issues and pull
requests, commenting, and replying to review comments
**Risk:** Can open, close and comment if the token is compromised. Cannot
change code.

### 3.3 Merge and Release Token

Add **write** on **Contents**, and on **Actions** if runs are to be triggered
or re-run.

**Capabilities:** the above plus `merge_pull_request_tool`,
`create_release_tool`, `trigger_workflow_tool` and the `rerun_*` tools
**Risk:** Contents: write is also the permission to push commits and tags;
GitHub offers nothing narrower for merging. A compromised token can change the
default branch wherever branch rules allow it, and a published release fires
the repository's `on: release` workflows. Protect the default branch with
required checks: `merge_pull_request_tool` refuses to merge unless they are
green (2.7), and without any it refuses unless told otherwise.

A release whose target commit changes a file under `.github/workflows/`,
relative to the default branch, additionally needs **Workflows: write**;
without it GitHub answers 404. Expect the same of a merge that brings workflow
changes in.

### 3.4 Permission per Tool

| Tool | Fine-grained permission |
|------|-------------------------|
| `list_issues_tool`, `get_issue_tool` | Issues: read |
| `create_issue_tool`, `update_issue_tool` | Issues: write |
| `create_issue_comment_tool` | Issues: write, or Pull requests: write on a PR |
| `list_pull_requests_tool`, `get_pull_request_tool`, `get_pull_request_diff_tool`, `list_pull_request_comments_tool` | Pull requests: read |
| `get_pull_request_checks_tool` | Pull requests: read, Commit statuses: read (see below) |
| `create_pull_request_tool`, `update_pull_request_tool`, `reply_to_review_comment_tool` | Pull requests: write |
| `merge_pull_request_tool` | Contents: write; Pull requests and Commit statuses: read (see 2.7) |
| `create_release_tool` | Contents: write |
| `list_workflow_runs_tool`, `get_workflow_run_tool`, `get_failed_job_logs_tool` | Actions: read |
| `trigger_workflow_tool`, `rerun_workflow_run_tool`, `rerun_failed_jobs_tool` | Actions: write |
| `get_file_content_tool`, `list_repo_tree_tool` | Contents: read |
| `search_code_tool`, `search_issues_tool` | None of their own (see below) |

`get_pull_request_checks_tool` and `merge_pull_request_tool` read check-runs, and GitHub's permission table
for fine-grained tokens lists no permission for that endpoint. It is readable
on public repositories; on a private repository use a classic token or a
GitHub App token. The search tools likewise have no permission of their own:
they return what the token can already read.

### 3.5 Recommended Scopes

For minimum privilege, grant only:
- Read on Contents, Issues, Pull requests and Actions — if you only need to read
- Add write on Issues and Pull requests — to comment, open and update
- Add write on Contents — only where the agent is meant to merge or release
  (merging needs no Administration permission: the gate reads branch
  protection from the branch itself)

## 4. Supply Chain Security

### 4.1 Automated CVE Scanning

This project uses GitHub Actions to automatically scan for CVEs:

1. **Scheduled Scans**: dependency audits on a regular cadence
2. **PR Checks**: every pull request is scanned before merge
3. **Dependabot**: enabled for automatic security updates

### 4.2 Container Security

The container image is built on **[Hummingbird Python](https://quay.io/repository/hummingbird/python)** from [Project Hummingbird](https://github.com/hummingbird-project):

| Advantage | Description |
|-----------|-------------|
| **Minimal CVE Count** | Dramatically reduced attack surface |
| **Rapid Security Updates** | Security patches applied promptly |
| **Python Optimized** | Pre-configured Python environment |
| **Non-Root Default** | Runs as non-root user |
| **Production Ready** | Proper signal handling, minimal footprint |

### 4.3 Events Logged

| Event | Level | Fields |
|-------|-------|--------|
| Server startup | INFO | version, GitHub API URL |
| GitHub API call | DEBUG | method, path (no auth headers) |
| Permission denied | WARN | required_scope |
| Rate limited | WARN | retry_after |
| Error | ERROR | error_type (no internals) |

### 4.4 Never Logged

- API tokens (any form)
- Full request/response bodies
- Issue/PR descriptions (may contain secrets)
- File content
- Job logs and the signed URLs they are downloaded from

## 5. Security Checklist

Before each release:

- [ ] All inputs validated
- [ ] No token exposure in logs or errors
- [ ] No filesystem writes
- [ ] No shell execution
- [ ] No eval/exec
- [ ] Rate limiting considered
- [ ] Error messages don't leak internals
- [ ] Dependencies scanned for CVEs
- [ ] Container rebuilt with latest Hummingbird base

## 6. Reporting Security Issues

Report security vulnerabilities using [GitHub's private security advisory](https://github.com/crunchtools/mcp-github/security/advisories/new). This creates a private channel visible only to maintainers.

Do NOT open public issues for security vulnerabilities.
