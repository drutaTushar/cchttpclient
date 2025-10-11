"""Model Context Protocol server exposing command metadata."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import typer
import uvicorn

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
    schema: Dict[str, Any]


class QueryResponse(BaseModel):
    results: List[CommandResponse]


class MCPApplication:
    def __init__(self, config_path: Path):
        self.config = CLIConfig.load(config_path)
        self.sections = parse_markdown_sections(self.config.markdown_path)
        self.store = EmbeddingStore(
            self.config.mcp.persist_path,
            self.config.mcp.embedding_model,
        )
        self._build_index()
        self.app = FastAPI(title="Dynamic CLI MCP Server")
        self._register_routes()

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
                embedding = self.store.model.encode(section.description, convert_to_numpy=True)
                records.append(
                    EmbeddingRecord(
                        section_id=section.identifier,
                        command=command.name,
                        subcommand=subcommand.name,
                        description=section.description,
                        schema=schema,
                        embedding=embedding,
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
