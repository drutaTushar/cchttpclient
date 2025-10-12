"""Model Context Protocol server exposing command metadata."""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import openai
import typer
import uvicorn

from .cli import CommandRuntime, _create_handler
from .config import CLIConfig
from .embedding import EmbeddingRecord, EmbeddingStore


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


class GenerateCodeRequest(BaseModel):
    description: str
    processor_prompt: str
    method: str = "GET"
    url: str = ""


class CreateCommandRequest(BaseModel):
    command: str
    subcommand: str
    help: str = ""
    method: str = "GET"
    url: str
    prepare_code: str = ""
    response_code: str = ""


class DeleteCommandRequest(BaseModel):
    command: str
    subcommand: str


# MCP Protocol Models
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Dict[str, Any] | None = None
    error: Dict[str, Any] | None = None


class MCPTool(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]




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
                section_id = f"{command.name}.{subcommand.name}"
                
                # Create description from help text and code comments
                description = subcommand.help
                if subcommand.prepare_code:
                    # Extract comments from code as additional context
                    code_lines = subcommand.prepare_code.split('\n')
                    comments = [line.strip()[1:].strip() for line in code_lines if line.strip().startswith('#')]
                    if comments:
                        description += " " + " ".join(comments)
                
                schema = _serialize_schema(command.name, subcommand, description)
                records.append(
                    EmbeddingRecord(
                        section_id=section_id,
                        command=command.name,
                        subcommand=subcommand.name,
                        description=description,
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

            logger.info(f"Found subcommand definition: {payload.command}.{payload.subcommand}")
            
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

        @app.post("/generate-code")
        def generate_code(request: GenerateCodeRequest) -> Dict[str, str]:
            """Generate prepare and response code using OpenAI."""
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise HTTPException(status_code=400, detail="OpenAI API key not configured")
                
                client = openai.OpenAI(api_key=api_key)
                
                prompt = f"""
                Generate EXACTLY two Python functions for a CLI command. Do not include any other code, explanations, imports, main functions, or example usage.

                Requirements:
                - Command Description: {request.description}
                - Processing Instructions: {request.processor_prompt}
                - HTTP Method: {request.method}
                - URL Template: {request.url}

                STRICT FORMAT REQUIREMENTS:
                1. Generate ONLY these two functions, nothing else
                2. No imports, no main function, no example code
                3. No markdown code blocks or backticks
                4. No explanatory text before or after the functions

                Function 1: prepare(request, helpers)
                - Takes a request dict with: method, url, headers, params, json, data
                - Returns the modified request dict
                - Available helpers: 
                  * helpers.secret(name): Get configured secrets
                  * helpers.env(key, default): Get environment variables
                  * helpers.json(value): Parse/serialize JSON data
                  * helpers.dumps(value): Serialize to JSON string
                  * helpers.loads(value): Parse JSON string

                Function 2: process_response(response, helpers)
                - Takes the HTTP response (already parsed dict/list for JSON responses, string for text)
                - Returns processed data for CLI output (dict, list, or string)
                - Available helpers: 
                  * helpers.secret(name): Get configured secrets
                  * helpers.env(key, default): Get environment variables  
                  * helpers.json(value): Parse/serialize JSON data
                  * helpers.get(dict, key, default): Safe dict access
                  * helpers.filter(items, key, value): Filter list of dicts
                  * helpers.map(items, keys): Extract specific keys from dicts

                Example format (adapt to requirements):
                def prepare(request, helpers):
                    return request

                def process_response(response, helpers):
                    return response

                Generate functions that match the description and processing requirements above.
                """

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a Python code generator. You MUST output ONLY the two requested functions with NO additional code, imports, explanations, or markdown. Follow the format exactly."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=800
                )

                generated_code = response.choices[0].message.content.strip()
                
                # Clean up any markdown artifacts
                generated_code = generated_code.replace('```python', '').replace('```', '').strip()
                
                # Split the code into prepare and response functions
                code_lines = generated_code.split('\n')
                prepare_lines = []
                response_lines = []
                current_function = None
                indent_level = 0
                
                for line in code_lines:
                    stripped = line.strip()
                    
                    # Skip empty lines outside functions
                    if not stripped and current_function is None:
                        continue
                    
                    # Skip main function and imports
                    if (stripped.startswith('def main(') or 
                        stripped.startswith('if __name__') or
                        stripped.startswith('import ') or
                        stripped.startswith('from ')):
                        current_function = 'skip'
                        continue
                    
                    # Detect function starts
                    if stripped.startswith('def prepare('):
                        current_function = 'prepare'
                        prepare_lines.append(line)
                        indent_level = len(line) - len(line.lstrip())
                    elif stripped.startswith('def process_response('):
                        current_function = 'response'
                        response_lines.append(line)
                        indent_level = len(line) - len(line.lstrip())
                    elif current_function == 'prepare':
                        # Continue with prepare function
                        if stripped and (len(line) - len(line.lstrip())) <= indent_level and not line.startswith(' ') and not line.startswith('\t'):
                            # Function ended, check if it's another function
                            if not stripped.startswith('def '):
                                current_function = None
                        if current_function == 'prepare':
                            prepare_lines.append(line)
                    elif current_function == 'response':
                        # Continue with response function  
                        if stripped and (len(line) - len(line.lstrip())) <= indent_level and not line.startswith(' ') and not line.startswith('\t'):
                            # Function ended, check if it's another function
                            if not stripped.startswith('def '):
                                current_function = None
                        if current_function == 'response':
                            response_lines.append(line)
                    elif current_function == 'skip':
                        # Skip until we find a proper function or reach base indentation
                        if stripped and not line.startswith(' ') and not line.startswith('\t'):
                            current_function = None
                
                prepare_code = '\n'.join(prepare_lines) if prepare_lines else "def prepare(request, helpers):\n    return request"
                response_code = '\n'.join(response_lines) if response_lines else "def process_response(response, helpers):\n    return response"
                
                return {
                    "prepare_code": prepare_code,
                    "response_code": response_code
                }
                
            except Exception as e:
                logging.error(f"Code generation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Code generation failed: {str(e)}")

        @app.post("/commands")
        def create_command(request: CreateCommandRequest) -> Dict[str, str]:
            """Create a new command in the configuration."""
            try:
                # Load current config
                config_data = json.loads(self.config_path.read_text())
                
                # Find or create command group
                command_group = None
                for cmd in config_data.get("commands", []):
                    if cmd["name"] == request.command:
                        command_group = cmd
                        break
                
                if not command_group:
                    command_group = {
                        "name": request.command,
                        "help": f"{request.command} commands",
                        "subcommands": []
                    }
                    config_data.setdefault("commands", []).append(command_group)
                
                # Check if subcommand already exists
                for subcmd in command_group["subcommands"]:
                    if subcmd["name"] == request.subcommand:
                        raise HTTPException(status_code=400, detail="Subcommand already exists")
                
                # Create new subcommand
                new_subcommand = {
                    "name": request.subcommand,
                    "help": request.help,
                    "prepare_code": request.prepare_code or "def prepare(request, helpers):\n    return request",
                    "response_code": request.response_code or "def process_response(response, helpers):\n    return response",
                    "arguments": [],
                    "request": {
                        "method": request.method,
                        "url": request.url,
                        "headers": {"Content-Type": "application/json"} if request.method in ["POST", "PUT", "PATCH"] else {},
                        "query": {},
                        "body": {"mode": "json", "template": {}},
                        "response": {"mode": "json", "success_codes": [200]}
                    }
                }
                
                command_group["subcommands"].append(new_subcommand)
                
                # Save config
                self.config_path.write_text(json.dumps(config_data, indent=2))
                self._reload_config()
                
                return {"status": "created"}
                
            except Exception as e:
                logging.error(f"Command creation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Command creation failed: {str(e)}")

        @app.delete("/commands")
        def delete_command(request: DeleteCommandRequest) -> Dict[str, str]:
            """Delete a command from the configuration."""
            try:
                # Load current config
                config_data = json.loads(self.config_path.read_text())
                
                # Find and remove subcommand
                for cmd in config_data.get("commands", []):
                    if cmd["name"] == request.command:
                        cmd["subcommands"] = [
                            sub for sub in cmd["subcommands"] 
                            if sub["name"] != request.subcommand
                        ]
                        break
                
                # Save config
                self.config_path.write_text(json.dumps(config_data, indent=2))
                self._reload_config()
                
                return {"status": "deleted"}
                
            except Exception as e:
                logging.error(f"Command deletion failed: {e}")
                raise HTTPException(status_code=500, detail=f"Command deletion failed: {str(e)}")

        # Validated Queries API endpoints
        @app.get("/validated-queries")
        def get_validated_queries():
            """Get all validated queries."""
            try:
                if not self.store:
                    return {"results": []}
                
                queries = self.store.get_all_validated_queries()
                return {"results": queries}
            except Exception as e:
                logging.error(f"Failed to get validated queries: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get validated queries: {str(e)}")

        @app.post("/validated-queries")
        def add_validated_query(request: Dict[str, Any]):
            """Add a new validated query mapping."""
            try:
                if not self.store:
                    raise HTTPException(status_code=500, detail="Embedding store not initialized")
                
                query_text = request.get("query_text")
                command = request.get("command")
                subcommand = request.get("subcommand")
                confidence = request.get("confidence", 1.0)
                
                if not query_text or not command or not subcommand:
                    raise HTTPException(status_code=400, detail="Missing required fields: query_text, command, subcommand")
                
                success = self.store.add_validated_query(query_text, command, subcommand, confidence)
                if success:
                    return {"status": "added", "query_text": query_text, "command": command, "subcommand": subcommand}
                else:
                    raise HTTPException(status_code=500, detail="Failed to add validated query")
                    
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Failed to add validated query: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to add validated query: {str(e)}")

        @app.delete("/validated-queries/{query_id}")
        def delete_validated_query(query_id: int):
            """Delete a validated query by ID."""
            try:
                if not self.store:
                    raise HTTPException(status_code=500, detail="Embedding store not initialized")
                
                success = self.store.remove_validated_query(query_id)
                if success:
                    return {"status": "deleted", "query_id": query_id}
                else:
                    raise HTTPException(status_code=404, detail="Validated query not found")
                    
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Failed to delete validated query: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to delete validated query: {str(e)}")

        @app.get("/ui", response_class=HTMLResponse)
        def ui_page() -> HTMLResponse:
            static_path = Path(__file__).parent.parent.parent / "static" / "admin.html"
            if static_path.exists():
                return HTMLResponse(static_path.read_text())
            else:
                return HTMLResponse("<h1>Admin UI not found</h1><p>Static file missing: admin.html</p>")


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

