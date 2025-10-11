# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the CLI
```bash
python -m dynamic_cli.cli --config config/cli_config.json <command> <subcommand> [options]
```

### Starting the MCP Server
```bash
python -m dynamic_cli.mcp_server serve --config config/cli_config.json --host 0.0.0.0 --port 8765
```

### Code Quality
```bash
# Format code
black src/

# Sort imports
isort src/

# Type checking
mypy src/

# Run tests
pytest
```

### Installing Dependencies
```bash
# Install with development dependencies
pip install -e ".[development]"
```

## Architecture Overview

This is a dual-purpose Python project consisting of:

1. **Dynamic CLI** (`src/dynamic_cli/cli.py`): A Typer-based HTTP client that builds commands dynamically from JSON configuration
2. **MCP Server** (`src/dynamic_cli/mcp_server.py`): A FastAPI server exposing command metadata via REST endpoints with semantic search

### Core Components

- **Configuration System** (`config.py`): Typed dataclasses for loading JSON configuration with secrets, commands, and MCP settings
- **Markdown Parser** (`markdown_parser.py`): Parses command behavior scripts stored in Markdown sections with YAML frontmatter
- **Script Execution** (`scripting.py`): Sandboxed execution environment for request preparation and response processing scripts
- **Embedding Store** (`embedding.py`): SQLite-backed vector store using OpenAI embeddings API for semantic command search

### Request Flow

1. CLI arguments are mapped to HTTP request components (path, query, headers, JSON body) based on JSON configuration
2. The corresponding Markdown script section is loaded and executed via `prepare(request, helpers)` 
3. HTTP request is made with `httpx`
4. Response is processed via `process_response(response, helpers)` before output

### Configuration Structure

- `config/cli_config.json`: Main configuration defining commands, secrets, and MCP settings
- `config/commands.md`: Markdown sections with YAML metadata containing Python scripts for request/response processing
- Each command references a `script_section` that must exist in the Markdown file

### Script Environment

Scripts in Markdown sections have access to a `helpers` object providing:
- `helpers.secret(name)`: Resolve configured secrets (env vars, files, commands, literal values)
- `helpers.env(name, default=None)`: Environment variable access
- `helpers.json(value)`: JSON serialization helper

### MCP Integration

The MCP server provides semantic search over command descriptions using OpenAI embeddings. For offline development, set `DYNAMIC_CLI_USE_HASH_EMBEDDINGS=1` to use deterministic hash-based embeddings instead.

## Development Notes

- Use Python 3.11+ for development
- The project uses uv for dependency management (see `uv.lock`)
- Configuration files in `config/` define both CLI behavior and MCP server settings
- Scripts are hot-loaded from Markdown, allowing runtime behavior changes without code modifications
- HTTP timeout defaults to 30 seconds but can be overridden per-request or globally