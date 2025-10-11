"""Model Context Protocol server exposing command metadata."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import typer
import uvicorn

from .cli import CommandRuntime, _create_handler
from .config import CLIConfig
from .embedding import EmbeddingRecord, EmbeddingStore
from .markdown_parser import parse_markdown_sections


class QueryRequest(BaseModel):
    query: str
    top_k: int | None = None


class CommandResponse(BaseModel):
    command: str
    subcommand: str
    section_id: str
    description: str
    score: float
    request_schema: Dict[str, Any] = Field(alias="schema")


class QueryResponse(BaseModel):
    results: List[CommandResponse]


class TestCommandRequest(BaseModel):
    command: str
    subcommand: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


_UI_HTML = """
<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Dynamic CLI Control Panel</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; background: #f5f5f5; }
      h1 { margin-top: 0; }
      section { background: white; padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
      textarea { width: 100%; min-height: 260px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
      button { padding: 0.5rem 1rem; margin-right: 0.5rem; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; }
      tr:hover { background: #f0f0f0; }
      label { display: block; font-weight: 600; margin-bottom: 0.25rem; }
      input[type="text"], input[type="number"] { width: 100%; padding: 0.4rem; margin-bottom: 0.6rem; }
      #test-output { white-space: pre-wrap; background: #111; color: #e5e5e5; padding: 1rem; border-radius: 6px; min-height: 80px; }
    </style>
  </head>
  <body>
    <h1>Dynamic CLI Control Panel</h1>
    <section>
      <h2>Command Catalog</h2>
      <p>Use semantic search through the MCP API or inspect the current commands here.</p>
      <table id="command-table">
        <thead>
          <tr><th>Command</th><th>Subcommand</th><th>Description</th></tr>
        </thead>
        <tbody></tbody>
      </table>
      <button id="refresh-commands">Refresh</button>
    </section>
    <section>
      <h2>Configuration</h2>
      <p>Edit the configuration JSON and press <strong>Save</strong> to persist the changes. The MCP index reloads automatically.</p>
      <textarea id="config-editor"></textarea>
      <div style="margin-top:0.75rem;">
        <button id="save-config">Save</button>
        <button id="reload-config">Reload</button>
        <span id="config-status"></span>
      </div>
    </section>
    <section>
      <h2>Command Test Harness</h2>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem;">
        <div>
          <label for="test-command">Command</label>
          <input type="text" id="test-command" placeholder="e.g. storage" />
        </div>
        <div>
          <label for="test-subcommand">Subcommand</label>
          <input type="text" id="test-subcommand" placeholder="e.g. upload" />
        </div>
      </div>
      <label for="test-arguments">Arguments JSON</label>
      <textarea id="test-arguments" style="min-height:140px;" placeholder='{"bucket": "demo", "payload": "{...}"}'></textarea>
      <div style="margin-top:0.75rem;">
        <button id="run-test">Run</button>
        <span id="test-status"></span>
      </div>
      <h3>Result</h3>
      <pre id="test-output"></pre>
    </section>
    <script>
      async function fetchCommands() {
        const response = await fetch('/commands');
        const data = await response.json();
        const tbody = document.querySelector('#command-table tbody');
        tbody.innerHTML = '';
        data.results.forEach((item) => {
          const row = document.createElement('tr');
          row.innerHTML = `<td>${item.command}</td><td>${item.subcommand}</td><td>${item.description}</td>`;
          tbody.appendChild(row);
        });
      }

      async function loadConfig() {
        const response = await fetch('/config');
        const data = await response.json();
        document.getElementById('config-editor').value = data.content;
        document.getElementById('config-status').textContent = 'Loaded';
      }

      async function saveConfig() {
        const content = document.getElementById('config-editor').value;
        const response = await fetch('/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content })
        });
        if (response.ok) {
          document.getElementById('config-status').textContent = 'Saved';
          fetchCommands();
        } else {
          const data = await response.json();
          document.getElementById('config-status').textContent = data.detail || 'Save failed';
        }
      }

      async function runTest() {
        const command = document.getElementById('test-command').value;
        const subcommand = document.getElementById('test-subcommand').value;
        let argsText = document.getElementById('test-arguments').value;
        let args = {};
        if (argsText.trim()) {
          try {
            args = JSON.parse(argsText);
          } catch (err) {
            document.getElementById('test-status').textContent = 'Invalid JSON';
            return;
          }
        }
        const response = await fetch('/test-command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command, subcommand, arguments: args })
        });
        if (response.ok) {
          const data = await response.json();
          document.getElementById('test-output').textContent = typeof data.output === 'string' ? data.output : JSON.stringify(data.output, null, 2);
          document.getElementById('test-status').textContent = 'Success';
        } else {
          const data = await response.json();
          document.getElementById('test-status').textContent = data.detail || 'Error running command';
          document.getElementById('test-output').textContent = '';
        }
      }

      document.getElementById('refresh-commands').addEventListener('click', fetchCommands);
      document.getElementById('reload-config').addEventListener('click', loadConfig);
      document.getElementById('save-config').addEventListener('click', saveConfig);
      document.getElementById('run-test').addEventListener('click', runTest);

      fetchCommands();
      loadConfig();
    </script>
  </body>
</html>
"""


class MCPApplication:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._load_config()
        self.store = EmbeddingStore.from_settings(self.config.mcp)
        self._build_index()
        self.app = FastAPI(title="Dynamic CLI MCP Server")
        self._register_routes()

    def _load_config(self) -> None:
        self.config = CLIConfig.load(self.config_path)
        self.sections = parse_markdown_sections(self.config.markdown_path)

    def _reload_config(self) -> None:
        previous_store = getattr(self, "store", None)
        self._load_config()
        previous_path = getattr(previous_store, "path", None)
        if previous_path is None or previous_path != self.config.mcp.persist_path:
            self.store = EmbeddingStore.from_settings(self.config.mcp)
        self._build_index()

    def _build_index(self):
        records: List[EmbeddingRecord] = []
        for command in self.config.commands:
            for subcommand in command.subcommands:
                section = self.sections.get(subcommand.script_section)
                if not section:
                    raise ValueError(
                        f"Missing Markdown section '{subcommand.script_section}' for {command.name}.{subcommand.name}"
                    )
                schema = _serialize_schema(command.name, subcommand, section.description)
                records.append(
                    EmbeddingRecord(
                        section_id=section.identifier,
                        command=command.name,
                        subcommand=subcommand.name,
                        description=section.description,
                        schema=schema,
                    )
                )
        self.store.rebuild(records)

    def _register_routes(self):
        app = self.app

        @app.get("/commands")
        def list_commands() -> QueryResponse:
            records = self.store.all()
            results = [
                CommandResponse(
                    command=record.command,
                    subcommand=record.subcommand,
                    section_id=record.section_id,
                    description=record.description,
                    score=0.0,
                    schema=record.schema,
                )
                for record in records
            ]
            return QueryResponse(results=results)

        @app.post("/query")
        def query_endpoint(request: QueryRequest) -> QueryResponse:
            if not request.query.strip():
                raise HTTPException(status_code=400, detail="Query must not be empty")
            matches = self.store.query(request.query, top_k=request.top_k or self.config.mcp.top_k)
            results = [
                CommandResponse(
                    command=record.command,
                    subcommand=record.subcommand,
                    section_id=record.section_id,
                    description=record.description,
                    score=score,
                    schema=record.schema,
                )
                for record, score in matches
            ]
            return QueryResponse(results=results)

        @app.get("/config")
        def read_config() -> Dict[str, Any]:
            return {"content": self.config_path.read_text(encoding="utf-8")}

        class ConfigUpdateRequest(BaseModel):
            content: str

        @app.put("/config")
        def update_config(payload: ConfigUpdateRequest) -> Dict[str, Any]:
            try:
                parsed = json.loads(payload.content)
            except json.JSONDecodeError as exc:  # pragma: no cover - validated in UI usage
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

            self.config_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            self._reload_config()
            return {"status": "ok"}

        @app.post("/test-command")
        def test_command(payload: TestCommandRequest = Body(...)) -> Dict[str, Any]:
            import logging
            logging.basicConfig(level=logging.INFO)
            logger = logging.getLogger(__name__)
            
            logger.info(f"Test command request: command={payload.command}, subcommand={payload.subcommand}, args={payload.arguments}")
            
            runtime = CommandRuntime(self.config)
            command = next((cmd for cmd in self.config.commands if cmd.name == payload.command), None)
            if not command:
                logger.error(f"Command '{payload.command}' not found. Available commands: {[cmd.name for cmd in self.config.commands]}")
                raise HTTPException(status_code=404, detail="Command not found")
            subcommand = next((sub for sub in command.subcommands if sub.name == payload.subcommand), None)
            if not subcommand:
                logger.error(f"Subcommand '{payload.subcommand}' not found in command '{payload.command}'. Available subcommands: {[sub.name for sub in command.subcommands]}")
                raise HTTPException(status_code=404, detail="Subcommand not found")

            logger.info(f"Found subcommand definition: {subcommand.script_section}")
            
            handler = _create_handler(runtime, subcommand)
            buffer = io.StringIO()
            try:
                logger.info(f"Executing handler with arguments: {payload.arguments}")
                with contextlib.redirect_stdout(buffer):
                    handler(**payload.arguments)
                logger.info("Handler executed successfully")
            except Exception as exc:  # pragma: no cover - runtime errors surfaced to client
                logger.error(f"Handler execution failed: {exc}")
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            output = buffer.getvalue().strip()
            logger.info(f"Handler output: {output}")
            try:
                parsed_output = json.loads(output)
            except json.JSONDecodeError:
                parsed_output = output
            return {"output": parsed_output}

        @app.get("/ui", response_class=HTMLResponse)
        def ui_page() -> HTMLResponse:
            return HTMLResponse(_UI_HTML)


def _serialize_schema(command_name: str, subcommand, description: str) -> Dict[str, Any]:
    return {
        "command": command_name,
        "subcommand": subcommand.name,
        "description": description or subcommand.help,
        "arguments": [
            {
                "name": arg.name,
                "help": arg.help,
                "type": arg.type,
                "required": arg.required,
                "location": arg.location,
                "target": arg.target,
            }
            for arg in subcommand.arguments
        ],
        "request": {
            "method": subcommand.request.method,
            "url": subcommand.request.url,
            "headers": subcommand.request.headers,
            "query": subcommand.request.query,
            "body": {
                "mode": subcommand.request.body.mode,
                "template": subcommand.request.body.template,
            },
            "response": {
                "mode": subcommand.request.response.mode,
                "success_codes": subcommand.request.response.success_codes,
            },
        },
    }

def create_app(config_path: Path) -> FastAPI:
    return MCPApplication(config_path).app


cli = typer.Typer(help="Dynamic CLI MCP server")


@cli.command()
def serve(
    config: Path = typer.Option(..., "--config", help="Path to CLI configuration"),
    host: str = typer.Option("127.0.0.1", help="Host to bind"),
    port: int = typer.Option(8765, help="Port to bind"),
):
    """Run the MCP server."""

    app = create_app(config)
    uvicorn.run(app, host=str(host), port=int(port))


if __name__ == "__main__":
    cli()

