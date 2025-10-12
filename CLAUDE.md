# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the CLI

**Path-Independent Installation Options:**

**Option 1: Global install (Recommended)**
```bash
# Install globally with uv
uv tool install .

# Then use from anywhere
dynamic-cli jp users
dynamic-cli storage list my-bucket --prefix data/
```

**Option 2: Shell wrapper script**
```bash
# Add project bin to PATH
export PATH="/path/to/dynamic-cli/bin:$PATH"

# Then use from anywhere
dynamic-cli jp users
```

**Option 3: Smart alias (changes to project directory)**
```bash
# Add to your shell profile (.bashrc, .zshrc, etc.)
alias dynamic-cli='(cd /path/to/dynamic-cli && uv run -m dynamic_cli.cli --config config/cli_config.json)'

# Use from anywhere - automatically changes to project directory
dynamic-cli jp users
```

**Option 4: Direct command (development)**
```bash
# From project directory only
uv run -m dynamic_cli.cli --config config/cli_config.json jp users
```

**Config file resolution:**
The CLI automatically looks for config files in this order:
1. `./.dynamic-cli/config.json` (project-specific - **recommended**)
2. `./.dynamic-cli/cli_config.json` (project-specific alternative)
3. `./cli_config.json` (current directory)
4. `./config/cli_config.json` (current directory)
5. `$DYNAMIC_CLI_CONFIG` (environment variable override)
6. `~/.config/dynamic-cli/config.json` (user fallback)
7. `~/.dynamic-cli/config.json` (user fallback)
8. `/etc/dynamic-cli/config.json` (system-wide fallback)

**Project-specific setup (recommended):**
```bash
# Method 1: Use the initialization script (easiest)
/path/to/dynamic-cli/bin/dynamic-cli-init
# or for new project:
/path/to/dynamic-cli/bin/dynamic-cli-init my-new-project

# Method 2: Manual setup
mkdir .dynamic-cli
cp /path/to/template/config.json .dynamic-cli/config.json
# Edit .dynamic-cli/config.json for project-specific commands
```

### Starting the MCP Server (Admin UI)
```bash
# Using the dedicated admin command (recommended)
dynamic-cli-admin

# Or with custom options  
dynamic-cli-admin --host 0.0.0.0 --port 8765

# Or using the module directly
uv run -m dynamic_cli.admin_server serve --config config/cli_config.json --host 0.0.0.0 --port 8765
```

### Starting the MCP Server (for LLM integration)
```bash
# Network transport (default: localhost:8001)
uv run python dynamic_cli_mcp_server.py --config config/cli_config.json

# Custom host and port
uv run python dynamic_cli_mcp_server.py --config config/cli_config.json --host 0.0.0.0 --port 8001
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

### MCP Integration

The project provides two MCP server implementations:

1. **Admin UI Server** (`admin_server.py`): FastAPI-based web interface for command management
   - **Admin web interface** at `/ui` for command management  
   - **AI code generation** using OpenAI GPT-4o to generate prepare/response functions
   - **Command CRUD operations** via REST API
   - **Query validation management** for validated query mappings

2. **MCP Server** (`dynamic_cli_mcp_server.py`): Standard MCP protocol implementation  
   - **Semantic command search tool** for LLMs to find relevant CLI commands
   - **Network transport (SSE)** for easy debugging and connection
   - **Query caching** and **validated queries** for improved performance
   - **Compatible with MCP Inspector** and other MCP clients
   - **Returns CLI command templates** with argument examples

### LLM Integration Flow

1. LLM receives user query (e.g., "list storage objects")
2. LLM calls `semantic_command_search` tool with the query
3. MCP server returns matching commands with CLI syntax
4. LLM can execute the suggested CLI command using bash

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