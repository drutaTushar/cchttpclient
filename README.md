# Dynamic CLI & MCP Server

This project provides a configurable command-line HTTP client together with a
Model Context Protocol (MCP) server. Both components load their behaviour from a
shared JSON configuration file and executable scripts stored in a Markdown
document.

## Project layout

```
config/
  cli_config.json   # Main configuration file shared by CLI and MCP server
  commands.md       # Markdown sections describing command behaviour & scripts
src/dynamic_cli/
  cli.py            # Dynamic Typer-based CLI entry point
  config.py         # Typed configuration loader
  embedding.py      # SQLite-backed embedding store with OpenAI vectors
  markdown_parser.py# Markdown section parser
  mcp_server.py     # FastAPI MCP server
  scripting.py      # Script execution helpers exposed to Markdown sections
```

## Configuration format

`config/cli_config.json` drives both the CLI and the MCP server. The most
important keys are:

- `markdown_path`: path to the Markdown file that stores command descriptions
  and request/response scripts.
- `commands`: array of top-level commands. Each command contains:
  - `name` and `help` text.
  - `subcommands`: an array of subcommand definitions. Every subcommand
    references a `script_section` identifier from the Markdown file and defines
    argument metadata plus a base HTTP request description.
- `secrets`: named secret descriptors. Supported types include `env`, `value`,
  `file`, and `command`. Scripts can request these via `helpers.secret(name)`.
- `mcp`: configuration for the MCP server embedding store. Provide the
  `embedding_model` (e.g. `text-embedding-3-small`), `persist_path` for the
  SQLite cache, and `api_key_env`/`api_base` values that identify how to call
  the OpenAI embeddings API.
- `http_timeout`: optional global timeout applied to outbound HTTP requests.

### Argument definitions

Arguments in the JSON schema declare how CLI parameters map to HTTP request
parts:

- `param_type`: `option` (default) generates a `--flag` style option; `argument`
  creates a positional argument.
- `location`: where the parsed value is inserted (`path`, `query`, `header`, or
  `json` for the request body).
- `target`: optional override for the key used inside the HTTP payload.
- `type`: controls CLI parsing. Supported primitives are `str`, `int`, `float`,
  `bool`, and `json` (which parses JSON strings into Python dictionaries).

### Scripts in Markdown

The Markdown file is divided into sections separated by lines containing three
hyphens. Each section begins with YAML metadata (`id`, `command`, and
`subcommand`), followed by free-form documentation and a Python code block. The
code must expose two callables:

```python
def prepare(request, helpers):
    """Mutate or replace the outbound HTTP request."""
    return request


def process_response(response, helpers):
    """Post-process the API response before it is returned."""
    return response
```

The `helpers` object inside scripts offers:

- `helpers.secret(name)`: resolve a named secret from the configuration (with
  support for environment variables, literal values, files, or shell commands).
- `helpers.env(name, default=None)`: fetch environment variables with an
  optional default.
- `helpers.json(value)`: convenience wrapper for `json.dumps`.

Scripts can freely modify headers, query parameters, URL, request body, or even
redirect the request entirely. Any unhandled exception surfaces as a CLI error.

## CLI usage

Run the CLI by pointing it at the configuration file:

```bash
python -m dynamic_cli.cli --config config/cli_config.json storage list my-bucket --prefix images/
```

The CLI builds the base HTTP request from the JSON schema, executes the relevant
`prepare` script for enrichment, performs the HTTP call with `httpx`, and then
hands the response to `process_response` for post-processing before printing the
result.

## MCP server

The MCP server exposes REST endpoints that LLMs (or other clients) can use to
retrieve command metadata, including enriched descriptions and request schemas.
Launch it with:

```bash
python -m dynamic_cli.mcp_server serve --config config/cli_config.json --host 0.0.0.0 --port 8765
```

Key endpoints:

- `GET /commands` – list all commands with schema metadata.
- `POST /query` – semantic search over command descriptions. The endpoint
  returns ranked matches, allowing an LLM to pick the most suitable command and
  assemble a valid request payload.

Embeddings are generated through the OpenAI embeddings REST API and cached in a
local SQLite database. When command descriptions or schemas change, only the
affected sections trigger a new API call. Set the environment variable named by
`mcp.api_key_env` (defaults to `OPENAI_API_KEY`). For offline development or
tests, define `DYNAMIC_CLI_USE_HASH_EMBEDDINGS=1` to switch to a deterministic
hash-based embedding generator.

### Administrative UI

Navigate to `GET /ui` to open a lightweight HTML control panel. It lists
commands, lets you edit and persist the shared configuration JSON, and provides
a small harness for running a command/subcommand pair against the configured
scripts to validate request enrichment behaviour without leaving the browser.

## Recommended stack

- **Language**: Python 3.11+
- **CLI framework**: [Typer](https://typer.tiangolo.com/) for ergonomic command
  definitions and automatic help generation.
- **HTTP client**: [httpx](https://www.python-httpx.org/) for robust async/sync
  HTTP requests.
- **Markdown parsing**: native parsing supplemented with `PyYAML` for front
  matter processing.
- **Scripting sandbox**: lightweight `exec`-based loader with a curated helper
  surface (`scripting.py`).
- **MCP server**: [FastAPI](https://fastapi.tiangolo.com/) with
  [Uvicorn](https://www.uvicorn.org/) for hosting, exposing the command
  retrieval tool over simple REST endpoints.
- **Vector store**: custom SQLite-backed store populated through the
  [OpenAI embeddings API](https://platform.openai.com/docs/guides/embeddings)
  with optional deterministic hashing for offline testing.

These choices keep the stack Python-centric, easy to deploy, and friendly to
embedded/offline scenarios.
