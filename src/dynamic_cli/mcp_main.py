#!/usr/bin/env python3
"""MCP server entry point with auto-config detection."""

import os
import sys
from pathlib import Path
from typing import Optional

from .admin_server import find_config_file


def main():
    """Main entry point for the MCP server that automatically finds config."""
    
    # Parse basic arguments
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("""
Dynamic CLI MCP Server

Usage:
  dynamic-cli-mcp [OPTIONS]

Options:
  --config PATH    Path to CLI configuration (auto-detected if not specified)
  --host TEXT      Host to bind [default: localhost]  
  --port INTEGER   Port to bind [default: 8001]
  --help          Show this message and exit

The MCP server provides semantic command search for LLM integration.
Connect your LLM client to the SSE endpoint.
""")
        return
    
    # Simple argument parsing
    config_path = None
    host = "localhost"
    port = 8001
    
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
        # Import and run the MCP server from the package
        from . import dynamic_cli_mcp_server
        
        # Override sys.argv with our parsed arguments
        original_argv = sys.argv[:]
        sys.argv = ["dynamic_cli_mcp_server.py", "--config", str(config_path), "--host", host, "--port", str(port)]
        
        dynamic_cli_mcp_server.main()
        
    except KeyboardInterrupt:
        print("\n👋 MCP server stopped")
    except Exception as e:
        print(f"❌ Server error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()