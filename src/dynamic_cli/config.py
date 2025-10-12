"""Configuration loading for the dynamic CLI and MCP server."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class SecretDefinition:
    """Description of how a secret value can be retrieved."""

    name: str
    type: str
    env: Optional[str] = None
    value: Optional[str] = None
    path: Optional[str] = None
    encoding: str = "utf-8"


@dataclass
class ArgumentDefinition:
    """Definition of a CLI argument or option."""

    name: str
    help: str = ""
    param_type: str = "option"  # "option" or "argument"
    cli_name: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    type: str = "str"
    required: bool = False
    default: Any = None
    location: str = "json"  # json, query, path, header
    target: Optional[str] = None


@dataclass
class RequestBodyDefinition:
    mode: str = "json"  # json or raw
    template: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseDefinition:
    mode: str = "json"
    success_codes: List[int] = field(default_factory=list)


@dataclass
class RequestDefinition:
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    query: Dict[str, Any] = field(default_factory=dict)
    body: RequestBodyDefinition = field(default_factory=RequestBodyDefinition)
    response: ResponseDefinition = field(default_factory=ResponseDefinition)
    timeout: Optional[float] = None


@dataclass
class SubcommandDefinition:
    name: str
    help: str
    arguments: List[ArgumentDefinition]
    prepare_code: str
    response_code: str
    request: RequestDefinition


@dataclass
class CommandDefinition:
    name: str
    help: str
    subcommands: List[SubcommandDefinition]


@dataclass
class MCPSettings:
    embedding_model: str
    persist_path: Path
    api_key_env: str = "OPENAI_API_KEY"
    api_base: Optional[str] = None
    collection_name: str = "command_descriptions"
    top_k: int = 3


@dataclass
class CLIConfig:
    commands: List[CommandDefinition]
    secrets: Dict[str, SecretDefinition]
    mcp: MCPSettings
    http_timeout: Optional[float] = None

    @classmethod
    def load(cls, path: Path) -> "CLIConfig":
        data = json.loads(Path(path).read_text())
        http_timeout = data.get("http_timeout")

        secrets = {
            name: SecretDefinition(name=name, **value)
            for name, value in data.get("secrets", {}).items()
        }

        def build_argument(arg_data: Dict[str, Any]) -> ArgumentDefinition:
            return ArgumentDefinition(**arg_data)

        def build_request(request_data: Dict[str, Any]) -> RequestDefinition:
            body_data = request_data.get("body", {})
            response_data = request_data.get("response", {})
            return RequestDefinition(
                method=request_data["method"],
                url=request_data["url"],
                headers=request_data.get("headers", {}),
                query=request_data.get("query", {}),
                body=RequestBodyDefinition(**body_data),
                response=ResponseDefinition(**response_data),
                timeout=request_data.get("timeout"),
            )

        commands: List[CommandDefinition] = []
        for command_data in data.get("commands", []):
            subcommands: List[SubcommandDefinition] = []
            for sub in command_data.get("subcommands", []):
                subcommands.append(
                    SubcommandDefinition(
                        name=sub["name"],
                        help=sub.get("help", ""),
                        arguments=[build_argument(arg) for arg in sub.get("arguments", [])],
                        prepare_code=sub.get("prepare_code", "def prepare(request, helpers):\n    return request"),
                        response_code=sub.get("response_code", "def process_response(response, helpers):\n    return response"),
                        request=build_request(sub["request"]),
                    )
                )
            commands.append(
                CommandDefinition(
                    name=command_data["name"],
                    help=command_data.get("help", ""),
                    subcommands=subcommands,
                )
            )

        mcp_data = data["mcp"]
        # Resolve persist_path relative to the config file directory
        persist_path = Path(mcp_data["persist_path"])
        if not persist_path.is_absolute():
            # Make relative paths relative to the config file directory
            persist_path = (path.parent / persist_path).resolve()
        else:
            persist_path = persist_path.expanduser()
        
        mcp_settings = MCPSettings(
            embedding_model=mcp_data["embedding_model"],
            persist_path=persist_path,
            api_key_env=mcp_data.get("api_key_env", "OPENAI_API_KEY"),
            api_base=mcp_data.get("api_base"),
            collection_name=mcp_data.get("collection_name", "command_descriptions"),
            top_k=mcp_data.get("top_k", 3),
        )

        return cls(
            commands=commands,
            secrets=secrets,
            mcp=mcp_settings,
            http_timeout=http_timeout,
        )
