"""Dynamic CLI and MCP server package."""

from __future__ import annotations

from typing import Any

__all__ = ["create_cli_app", "create_mcp_app"]


def create_cli_app(*args: Any, **kwargs: Any):
    """Create the CLI Typer application lazily to avoid heavy imports."""

    from .cli import create_app

    return create_app(*args, **kwargs)


def create_mcp_app(*args: Any, **kwargs: Any):
    """Create the MCP FastAPI application lazily."""

    from .mcp_server import create_app

    return create_app(*args, **kwargs)
