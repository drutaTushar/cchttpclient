#!/usr/bin/env python3
"""Admin server entry point with auto-config detection."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from .admin_server import find_config_file, create_app
import uvicorn


def main():
    """Main entry point for the admin server that automatically finds config."""
    
    # Parse basic arguments
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("""
Dynamic CLI Admin Server

Usage:
  dynamic-cli-admin [OPTIONS]

Options:
  --config PATH    Path to CLI configuration (auto-detected if not specified)
  --host TEXT      Host to bind [default: 127.0.0.1]  
  --port INTEGER   Port to bind [default: 8765]
  --help          Show this message and exit

The admin server provides a web interface for managing CLI commands.
It will automatically find your project's .dynamic-cli/config.json file.
""")
        return
    
    # Simple argument parsing
    config_path = None
    host = "127.0.0.1"
    port = 8765
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--config" and i + 1 < len(sys.argv):
            config_path = Path(sys.argv[i + 1])
            i += 2
        elif arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
            i += 2
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    
    # Auto-detect config if not provided
    if not config_path:
        config_path = find_config_file()
        if not config_path:
            print(
                "❌ No config file found. Please either:\n"
                "  • Create .dynamic-cli/config.json in current directory (project-specific)\n"
                "  • Create cli_config.json in current directory\n"
                "  • Use --config option to specify path explicitly",
                file=sys.stderr
            )
            sys.exit(1)
        print(f"📁 Using config: {config_path}")
    
    try:
        app = create_app(config_path)
        print(f"🌐 Admin interface available at: http://{host}:{port}/ui")
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n👋 Admin server stopped")
    except Exception as e:
        print(f"❌ Server error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()