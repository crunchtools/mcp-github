# Specification: Per-Request Token and Merge Gate

> **Spec ID:** 002-request-token-merge-gate
> **Status:** Implemented
> **Version:** 1.3.0
> **Author:** crunchtools.com
> **Date:** 2026-10-14

## Overview

Two changes, both about whose authority a call carries.

1. **Per-request token.** GitHub's hosted MCP server takes the caller's
   personal access token as `Authorization: Bearer <token>` on every HTTP
   request and acts with it. Behind an opt-in, this server does the same, so
   it can stand in for GitHub's server without the client changing.
2. **Merge gate.** The token an agent merges with may belong to an
   organization owner, and owners can bypass ruleset-required checks: GitHub
   would merge a pull request whose checks failed. `merge_pull_request_tool`
   now enforces the required checks itself.

No tools are added; the count stays at 25.

---

## Per-Request Token

| Setting | Incoming `Authorization` | Token used |
|---------|-------------------------|------------|
| `GITHUB_ACCEPT_REQUEST_TOKEN` off (default) | ignored | `GITHUB_TOKEN` (required) |
| on, HTTP request with `Bearer <token>` | used | the request's token |
| on, HTTP request without the header, or stdio | — | `GITHUB_TOKEN` |
| on, no header and no `GITHUB_TOKEN` | — | none: error before any API call |
| on, header present but malformed | refused | none: error, not forwarded |

- The header is read with `fastmcp.server.dependencies.get_http_headers(include={"authorization"})`,
  which returns `{}` outside an HTTP request.
- Accepted form: `(?i:bearer) ` followed by 1 to 1024 characters in
  `\x21`–`\x7e`, matched in full.
- The token is chosen in `GitHubClient._send` for each call and passed as
  that call's header. The shared `httpx.AsyncClient` has an `Authorization`
  default only when `GITHUB_TOKEN` is set.
- `errors.request_token` (a `ContextVar`) holds the request's token so that
  `GitHubApiError` scrubs it; each MCP request runs in its own task context.
- The job-log second hop (`get_redirected_tail`) still sends no token.

## Merge Gate

Before `PUT /repos/{owner}/{repo}/pulls/{n}/merge`:

| Step | Request | Refuses when |
|------|---------|--------------|
| 1 | `GET .../pulls/{n}` | caller `sha` is not the head; head or base missing |
| 2a | `GET .../rules/branches/{base}` (paged) | — |
| 2b | `GET .../branches/{base}` (`protection.required_status_checks`) | any error, or `protected` with no `protection` shown |
| 3 | — | no required checks, unless `allow_no_required_checks=True` |
| 4 | `GET .../commits/{head}/check-runs` and `.../status` (paged) | a required check is missing, pending or failed |
| 5 | `GET .../pulls/{n}` again | head or base changed since step 1 |
| 6 | `PUT .../merge` with `sha` = head | (GitHub: 405, 409) |

- A required check is `(context, app id or None)`. Rulesets give
  `integration_id`; classic protection gives `checks[].app_id`, where -1
  means any, or bare `contexts`.
- The most recent check run of the context's name (highest id) decides; it
  passes when completed with `success`, `skipped` or `neutral`. With an app
  id, only that app's runs count. With no app id and no run, the commit
  status of that context must be `success`.
- Each list is read up to 10 pages of 100; more refuses the merge.
- Refusals raise `MergeRefusedError` naming every offending check.

---

## Security Considerations

- Token mix-up between concurrent callers: nothing request-specific is
  stored on the shared client or in a global.
- A malformed header never falls back to `GITHUB_TOKEN`: a caller that
  meant to use its own token does not silently act as the server.
- The gate fails closed on unreadable protection, missing checks, oversized
  lists and branches without required checks.
- Required reviews and other rules are not re-enforced; the bypass still
  applies to them.

---

## Module Changes

| File | Changes |
|------|---------|
| `config.py` | `GITHUB_ACCEPT_REQUEST_TOKEN`; `token` may be None |
| `client.py` | `_incoming_token`, `_auth_headers`; conditional default `Authorization` |
| `errors.py` | `request_token`, `scrub_tokens`, `MergeRefusedError` |
| `tools/pull_requests.py` | Merge gate helpers; `allow_no_required_checks` |
| `server.py` | `allow_no_required_checks` on `merge_pull_request_tool`; docstring |

---

## Testing Requirements

- [x] stdio uses the env token; option off ignores the header (well-formed
      or not); option on prefers the header; header absent falls back
- [x] Request-token-only instance: no default `Authorization` on the client
- [x] No token at all: error and no HTTP request
- [x] Malformed headers refused and not sent: empty, no scheme, other
      scheme, extra spaces, tab, control, DEL, non-ASCII, over-long
- [x] Request token scrubbed from API and transport errors
- [x] Five concurrent requests with different tokens each send their own
      (real httpx client over a mock transport)
- [x] Gate: all green merges pinned to head; failing, pending, missing;
      newest status of a repeated context decides; unreadable rules, check
      runs, statuses or PR never merge; the MCP tool forwards the flag;
      head or base moving during the gate is refused;
      status pending/failure/error; most recent run decides; app-bound
      rule; no checks refused and allowed by flag; flag does not waive
      existing checks; `sha` mismatch; protection 403; classic `checks`
      and `contexts`; rulesets and classic combined; branch name encoded;
      check runs, statuses and rules paginated; page cap refuses

---

## Dependencies

- Depends on: 001-pr-merge-logs-release
- Blocks: none

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.3.0 | 2026-10-14 | Implemented |
