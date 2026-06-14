"""MCP GitHub CrunchTools - Secure MCP server for GitHub.

A security-focused MCP server for GitHub issues, pull requests (diffs and
CI checks), repository files, and code/issue search. Works with github.com
and GitHub Enterprise Server.

Usage:
    mcp-github-crunchtools

    python -m mcp_github_crunchtools

    uvx mcp-github-crunchtools

Environment Variables:
    GITHUB_TOKEN: Required. GitHub Personal Access Token.
    GITHUB_API_URL: Optional. API base URL (default: https://api.github.com).
    GITHUB_DEFAULT_ORG: Optional. Default owner when a tool omits owner.

Example with Claude Code:
    claude mcp add mcp-github-crunchtools \\
        --env GITHUB_TOKEN=your_token_here \\
        -- uvx mcp-github-crunchtools
"""

import argparse

from .server import mcp

__version__ = "0.1.0"
__all__ = ["main", "mcp"]


def main() -> None:
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="MCP server for GitHub")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to for HTTP transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8016,
        help="Port to bind to for HTTP transports (default: 8016)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)
