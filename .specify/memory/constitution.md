# mcp-github-crunchtools Constitution

> **Version:** 1.1.0
> **Ratified:** 2026-06-14
> **Amended:** 2026-10-02
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.21.0
> **Profile:** MCP Server

This file holds what is specific to mcp-github. The fleet rules and the MCP
Server profile (five-layer security model, two-layer tools, distribution
channels, transports, quality gates, Gourmand) apply at the inherited version
and are checked against this repo's files by `constitution.yml`. They are not
restated here.

## Security Model Specifics

- **Credentials:** `GITHUB_TOKEN` (required), held as `SecretStr`, read from
  the environment only. `GitHubApiError` scrubs it from messages, and
  `Config.__repr__()`/`__str__()` never expose it.
- **Input limits:** Pydantic models with `extra="forbid"`; issue and PR
  states are allowlisted (`open`, `closed`, `all`); owner and repo names are
  checked for injection characters; git refs follow check-ref-format
  rules (no `..`, `//` or leading/trailing `.` or `/`). `NotFoundError`
  truncates long identifiers.
- **API:** `Authorization: Bearer` header, never the URL; the
  `X-GitHub-Api-Version` header is pinned to `2022-11-28`; path parameters
  are URL-encoded; requests time out after 30s; responses are capped at 10MB.
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

Issues, pull requests, Actions, files and search. Client error handling is
tested for 401, 404, 429 and 204 responses in `TestClientErrorHandling`.

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
