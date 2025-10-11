#!/usr/bin/env python3
"""Global entry point for dynamic-cli that handles config path resolution."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from .cli import main as cli_main


def find_config_file() -> Optional[Path]:
    """Find the config file in various standard locations."""
    
    # List of possible config locations (in order of preference)
    possible_paths = [
        # Current working directory
        Path.cwd() / "cli_config.json",
        Path.cwd() / "config" / "cli_config.json",
        
        # User home directory
        Path.home() / ".config" / "dynamic-cli" / "config.json",
        Path.home() / ".dynamic-cli" / "config.json",
        
        # Environment variable
        Path(os.getenv("DYNAMIC_CLI_CONFIG", "")) if os.getenv("DYNAMIC_CLI_CONFIG") else None,
        
        # System-wide config
        Path("/etc/dynamic-cli/config.json"),
    ]
    
    for config_path in possible_paths:
        if config_path and config_path.exists():
            return config_path
    
    return None


def main():
    """Main entry point that automatically finds config and delegates to CLI."""
    
    # Check if --config is already provided
    if "--config" in sys.argv or "-c" in sys.argv:
        # User provided config explicitly, use normal CLI
        cli_main()
        return
    
    # Try to find config automatically
    config_path = find_config_file()
    
    if not config_path:
        typer.echo(
            "❌ No config file found. Please either:\n"
            "  • Create cli_config.json in current directory\n"
            "  • Create config/cli_config.json in current directory\n"
            "  • Set DYNAMIC_CLI_CONFIG environment variable\n"
            "  • Use --config option to specify path explicitly\n"
            "\nExample: dynamic-cli --config /path/to/config.json jp users",
            err=True
        )
        raise typer.Exit(1)
    
    # Insert config path into argv and delegate to CLI
    typer.echo(f"📁 Using config: {config_path}")
    sys.argv.insert(1, "--config")
    sys.argv.insert(2, str(config_path))
    
    cli_main()


if __name__ == "__main__":
    main()