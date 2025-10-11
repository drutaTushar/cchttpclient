# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the CLI
```bash
python -m dynamic_cli.cli --config config/cli_config.json <command> <subcommand> [options]
```

### Starting the MCP Server
```bash
python -m dynamic_cli.mcp_server --config config/cli_config.json --host 0.0.0.0 --port 8765
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
2. **MCP Server** (`src/dynamic_cli/mcp_server.py`): A FastAPI server with admin UI for creating commands and AI-powered code generation

### Core Components

- **Configuration System** (`config.py`): Typed dataclasses for loading JSON configuration with inline Python code, secrets, and MCP settings
- **Script Execution** (`scripting.py`): Sandboxed execution environment for request preparation and response processing scripts stored inline in JSON
- **Embedding Store** (`embedding.py`): SQLite-backed vector store using OpenAI embeddings API for semantic command search
- **Admin UI** (`static/admin.html`): Web interface for managing commands with AI-powered code generation

### Request Flow

1. CLI arguments are mapped to HTTP request components (path, query, headers, JSON body) based on JSON configuration
2. Inline `prepare_code` is executed via `prepare(request, helpers)` to modify the HTTP request
3. HTTP request is made with `httpx` (can be skipped if prepare returns None)
4. Response is processed via inline `response_code` through `process_response(response, helpers)` before output

### Configuration Structure

- `config/cli_config.json`: Single JSON file containing all commands with inline Python code for request/response processing
- `static/admin.html`: Web UI for creating and managing commands
- Each subcommand contains `prepare_code` and `response_code` fields with inline Python functions

### Script Environment

Inline scripts have access to a `helpers` object providing:
- `helpers.secret(name)`: Resolve configured secrets (env vars, files, commands, literal values)
- `helpers.env(name, default=None)`: Environment variable access
- `helpers.json(value)`: JSON serialization helper

### MCP Integration and Admin UI

The MCP server provides:
- **Semantic search** over command descriptions using OpenAI embeddings
- **Admin web interface** at `/ui` for command management
- **AI code generation** using OpenAI GPT-4o to generate prepare/response functions
- **Command CRUD operations** via REST API

For offline development, set `DYNAMIC_CLI_USE_HASH_EMBEDDINGS=1` to use deterministic hash-based embeddings instead of OpenAI.

### AI Code Generation

The admin UI can generate Python code for commands using OpenAI:
1. Provide a command description and processing instructions
2. AI generates `prepare()` and `process_response()` functions
3. Code is automatically inserted into the command configuration
4. Functions are executed at runtime with proper error handling

## Development Notes

- Use Python 3.11+ for development
- The project uses uv for dependency management (see `uv.lock`)
- All configuration is stored in a single JSON file with inline Python code
- No more Markdown dependency - everything is JSON-based
- Commands can be created and managed through the web UI
- Set `OPENAI_API_KEY` environment variable for AI code generation
- HTTP timeout defaults to 30 seconds but can be overridden per-request or globally