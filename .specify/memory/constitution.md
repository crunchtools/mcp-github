# mcp-github-crunchtools Constitution

> **Version:** 1.3.0
> **Ratified:** 2026-06-14
> **Amended:** 2026-10-14
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.24.0
> **Profile:** MCP Server

This file holds what is specific to mcp-github. The fleet rules and the MCP
Server profile (five-layer security model, two-layer tools, distribution
channels, transports, quality gates, Gourmand) apply at the inherited version
and are checked against this repo's files by `constitution.yml`. They are not
restated here.

## Security Model Specifics

- **Credentials:** `GITHUB_TOKEN`, held as `SecretStr`, read from the
  environment only; required unless `GITHUB_ACCEPT_REQUEST_TOKEN` is on, in
  which case an HTTP request's `Authorization: Bearer <token>` is used for
  that request (strict format, malformed refused, never stored on the shared
  client). `GitHubApiError` scrubs both tokens from messages, and
  `Config.__repr__()`/`__str__()` never expose the token.
- **Merge gate:** `merge_pull_request` merges only when every required
  status check of the base branch (rulesets and classic protection) passes
  on the head commit, pinned to that head; it fails closed when checks
  cannot be read, and when none are required unless the caller passes
  `allow_no_required_checks=True`.
- **Input limits:** Pydantic models with `extra="forbid"`; issue and PR
  states are allowlisted (`open`, `closed`, `all`), as are merge methods
  (`merge`, `squash`, `rebase`); owner and repo names are
  checked for injection characters; git refs follow check-ref-format
  rules (no `..`, `//` or leading/trailing `.` or `/`); an expected head SHA
  is a full 40 or 64 character hex SHA. `NotFoundError`
  truncates long identifiers.
- **API:** `Authorization: Bearer` header, never the URL; the
  `X-GitHub-Api-Version` header is pinned to `2022-11-28`; path parameters
  are URL-encoded; requests time out after 30s; responses are capped at 10MB.
- **Redirects:** the API client follows none. A job log, which GitHub serves
  as a redirect to a pre-signed storage URL, is fetched by a separate client
  that has no token, over HTTPS to a named host only, streamed, with only its
  tail kept. The signed URL is never logged or put in an error message.
- **Result caps:** tools that gather several pages say when they cut:
  300 items per kind for pull request comments, 300 jobs per run, and for
  failed-job logs 1000 lines per job, 5 jobs and 256 KiB per result.
- **Surface:** pure API wrappers. No filesystem access, shell execution or
  code evaluation.

## Any-Instance Compatibility

The server works with github.com and GitHub Enterprise Server:

| Variable | Purpose |
|----------|---------|
| `GITHUB_API_URL` | API base (default `https://api.github.com`); HTTPS required for non-localhost URLs |
| `GITHUB_DEFAULT_ORG` | Optional default owner |
| `SSL_CERT_FILE` | CA bundle for corporate CAs |
| `GITHUB_SSL_VERIFY` | Development escape hatch; disabling it logs a warning |

## Tool Groups

Issues, pull requests, Actions, releases, files and search: 25 tools, of which
14 only read. Client error handling is tested for 401, 404, 429 and 204
responses in `TestClientErrorHandling`.

## Instance

| Context | Name |
|---------|------|
| GitHub repo | `crunchtools/mcp-github` |
| PyPI package | `mcp-github-crunchtools` |
| Container image | `quay.io/crunchtools/mcp-github` |
| systemd service | `mcp-github.service` |
| HTTP port | 8016 |

## History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-06-14 | Initial constitution (ported from mcp-gitlab-crunchtools) |
| 1.0.1 | 2026-09-25 | Inherit constitution v1.17.0 (Gatehouse gates) |
| 1.1.0 | 2026-10-02 | Manifest under constitution v1.18.0: profile restatement removed, mcp-github specifics kept; `..` rule moved from file paths to git refs to match the code |
| 1.2.0 | 2026-10-12 | Seven tools for pull requests, Actions runs and logs, and releases (spec 001): redirect handling, result caps, merge-method and SHA validation, releases tool group |
| 1.3.0 | 2026-10-14 | Per-request token (`GITHUB_ACCEPT_REQUEST_TOKEN`) and the merge gate (spec 002) |
