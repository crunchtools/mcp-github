# MCP GitHub CrunchTools Container
# Built on Hummingbird Python image (Red Hat UBI-based) for enterprise security
#
# Build:
#   podman build -t quay.io/crunchtools/mcp-github .
#
# Run:
#   podman run -e GITHUB_TOKEN=your_token quay.io/crunchtools/mcp-github
#
# With Claude Code:
#   claude mcp add mcp-github-crunchtools \
#     --env GITHUB_TOKEN=your_token \
#     -- podman run -i --rm -e GITHUB_TOKEN quay.io/crunchtools/mcp-github

# Stage 1: Lock (turn uv.lock into the exact dependency set to install)
FROM quay.io/hummingbird/python:3.14-builder AS lock
USER 0
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /lock
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project \
      --format requirements-txt -o /requirements.txt

# Stage 2: Builder (has a shell, dnf and build tools)
FROM quay.io/hummingbird/python:3.14-builder AS builder
USER 0
WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
# Dependencies come from uv.lock, not from a fresh resolve. `pip install .`
# read only pyproject.toml, whose floors carry no upper bound, so the image
# shipped whatever had been released that morning -- a dependency set no test
# had ever run against. That is how google-genai 3.0 reached mcp-gemini's
# production with CI green (RT #1564, trentina issue #79 is the same bug).
# --no-deps stops pip re-resolving what the lock already decided.
COPY --from=lock /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# Stage 3: Runtime (distroless -- no shell, no package manager)
FROM quay.io/hummingbird/python:3.14

# Labels for container metadata
LABEL name="mcp-github-crunchtools" \
      version="2.1.1" \
      summary="Secure MCP server for GitHub issues, pull requests, Actions, releases, files, and search" \
      description="A security-focused MCP server for GitHub built on Red Hat UBI" \
      maintainer="crunchtools.com" \
      url="https://github.com/crunchtools/mcp-github" \
      io.k8s.display-name="MCP GitHub CrunchTools" \
      io.openshift.tags="mcp,github,devops" \
      org.opencontainers.image.source="https://github.com/crunchtools/mcp-github" \
      org.opencontainers.image.description="Secure MCP server for GitHub issues, pull requests, Actions, releases, files, and search" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

WORKDIR /app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Verify the install. Exec form: this stage has no /bin/sh for RUN's shell form.
RUN ["python3", "-c", "from mcp_github_crunchtools import main; print('Installation verified')"]

# Default: stdio transport (use -i with podman run)
# HTTP:    --transport streamable-http (use -d -p 8014:8014 with podman run)
EXPOSE 8014
ENTRYPOINT ["python", "-m", "mcp_github_crunchtools"]
