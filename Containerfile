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

# Stage 1: Builder (has a shell, dnf and build tools)
FROM quay.io/hummingbird/python:latest-builder AS builder
USER 0
WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Stage 2: Runtime (distroless -- no shell, no package manager)
FROM quay.io/hummingbird/python:latest

# Labels for container metadata
LABEL name="mcp-github-crunchtools" \
      version="0.3.0" \
      summary="Secure MCP server for GitHub issues, pull requests, files, and search" \
      description="A security-focused MCP server for GitHub built on Red Hat UBI" \
      maintainer="crunchtools.com" \
      url="https://github.com/crunchtools/mcp-github" \
      io.k8s.display-name="MCP GitHub CrunchTools" \
      io.openshift.tags="mcp,github,devops" \
      org.opencontainers.image.source="https://github.com/crunchtools/mcp-github" \
      org.opencontainers.image.description="Secure MCP server for GitHub issues, pull requests, files, and search" \
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
