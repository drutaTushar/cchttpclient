#!/usr/bin/env python3
"""Dynamic CLI MCP server with real semantic search using official MCP SDK."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
import uvicorn

# Import your existing modules
from .config import CLIConfig
from .embedding import EmbeddingStore, EmbeddingRecord

# Set up logging - minimal output for LLM consumption
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger("dynamic-cli-mcp-server")
logger.setLevel(logging.WARNING)

# Global variables for server state
config: CLIConfig | None = None
store: EmbeddingStore | None = None

# Create server instance
server = Server("dynamic-cli-mcp-server")

def initialize_server(config_path: Path) -> None:
    """Initialize the MCP server with configuration."""
    global config, store
    
    logger.info(f"Initializing server with config: {config_path}")
    
    # Load configuration
    config = CLIConfig.load(config_path)
    
    # Set up embedding store - use hash embeddings by default for demo
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["DYNAMIC_CLI_USE_HASH_EMBEDDINGS"] = "1"
        logger.info("Using hash embeddings (no OpenAI API key found)")
    
    store = EmbeddingStore.from_settings(config.mcp)
    
    # Build command index
    _build_command_index()
    
    logger.info("Server initialized successfully")

def _build_command_index() -> None:
    """Build the embedding index from available commands."""
    if not config or not store:
        return
        
    records: list[EmbeddingRecord] = []
    
    for command in config.commands:
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
            
            # Create schema info for the record
            schema = _create_command_schema(command.name, subcommand)
            
            records.append(
                EmbeddingRecord(
                    section_id=section_id,
                    command=command.name,
                    subcommand=subcommand.name,
                    description=description,
                    schema=schema,
                )
            )
    
    store.rebuild(records)
    logger.info(f"Built index with {len(records)} commands")

def _create_command_schema(command_name: str, subcommand) -> dict[str, Any]:
    """Create schema information for a command."""
    
    # Build argument schema
    arguments = []
    for arg in subcommand.arguments:
        arg_info = {
            "name": arg.name,
            "help": arg.help,
            "type": arg.type,
            "required": arg.required,
            "param_type": arg.param_type,  # "option" or "argument"
        }
        if arg.cli_name:
            arg_info["cli_name"] = arg.cli_name
        if arg.default is not None:
            arg_info["default"] = arg.default
        arguments.append(arg_info)
    
    return {
        "command": command_name,
        "subcommand": subcommand.name,
        "help": subcommand.help,
        "arguments": arguments,
        "http_method": subcommand.request.method,
        "url": subcommand.request.url,
    }

def _format_command_result(result: EmbeddingRecord, score: float, is_validated: bool = False) -> str:
    """Format a search result for LLM consumption."""
    
    schema = result.schema
    command_name = schema["command"]
    subcommand_name = schema["subcommand"]
    
    # Build CLI command template - truly path-independent
    cli_parts = ["dynamic-cli", command_name, subcommand_name]
    
    # Add argument examples
    argument_examples = []
    for arg in schema.get("arguments", []):
        if arg["param_type"] == "argument":
            # Positional argument
            example_value = _get_example_value(arg)
            cli_parts.append(example_value)
            argument_examples.append(f"  {arg['name']}: {example_value} ({arg['help']})")
        else:
            # Option argument
            cli_name = arg.get("cli_name", f"--{arg['name'].replace('_', '-')}")
            example_value = _get_example_value(arg)
            cli_parts.extend([cli_name, example_value])
            argument_examples.append(f"  {cli_name}: {example_value} ({arg['help']})")
    
    cli_command = " ".join(cli_parts)
    
    # Format the result
    result_text = f"""**Command**: {command_name} {subcommand_name}
**Description**: {schema['help']}
**CLI Command**: {cli_command}
**HTTP Method**: {schema.get('http_method', 'GET')}
**URL**: {schema.get('url', 'N/A')}

**Arguments**:
{chr(10).join(argument_examples) if argument_examples else '  No arguments required'}

**Setup**: Choose one installation method:
  • **Global install**: `uv tool install dynamic-cli` (recommended)
  • **Alias method**: `alias dynamic-cli='(cd /path/to/dynamic-cli && uv run -m dynamic_cli.cli --config config/cli_config.json)'`
  • **Script wrapper**: Create executable script with absolute paths
**Match Score**: {score:.3f}{' ✅ VALIDATED' if is_validated else ''}"""
    
    return result_text

def _get_example_value(arg: dict[str, Any]) -> str:
    """Generate example values for arguments based on their type and name."""
    arg_name = arg["name"].lower()
    arg_type = arg.get("type", "str")
    
    # Common examples based on argument names
    if "bucket" in arg_name:
        return "my-bucket"
    elif "file" in arg_name or "path" in arg_name:
        return "/path/to/file"
    elif "id" in arg_name:
        return "123"
    elif "name" in arg_name:
        return "example-name"
    elif "email" in arg_name:
        return "user@example.com"
    elif "url" in arg_name:
        return "https://api.example.com"
    elif "query" in arg_name or "sql" in arg_name:
        return "SELECT * FROM table"
    elif "message" in arg_name:
        return "hello world"
    elif "prefix" in arg_name:
        return "data/"
    
    # Type-based defaults
    elif arg_type == "int":
        return "42"
    elif arg_type == "float":
        return "3.14"
    elif arg_type == "bool":
        return "true"
    elif arg_type == "json":
        return '{"key": "value"}'
    else:
        return "example-value"

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="semantic_command_search",
            description="Search for CLI commands using semantic queries",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query to find matching commands"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls."""
    if name != "semantic_command_search":
        raise ValueError(f"Unknown tool: {name}")
    
    if not arguments or "query" not in arguments:
        raise ValueError("Missing required argument: query")
    
    if not store:
        return [types.TextContent(type="text", text="Error: Server not initialized")]
    
    query = arguments["query"]
    limit = min(arguments.get("limit", 3), 10)  # Cap at 10 results
    
    logger.info(f"Searching for: {query} (limit: {limit})")
    
    try:
        # Check if this is a validated query first
        validated_match = store.get_validated_query(query)
        is_validated = validated_match is not None
        
        # Perform semantic search
        results = store.query(query, top_k=limit)
        
        if not results:
            return [types.TextContent(
                type="text", 
                text=f"No commands found matching: {query}"
            )]
        
        # Apply confidence threshold - only return results above minimum score
        MIN_CONFIDENCE_SCORE = 0.4  # Adjust this threshold as needed
        filtered_results = [(record, score) for record, score in results if score >= MIN_CONFIDENCE_SCORE]
        
        if not filtered_results:
            best_score = results[0][1] if results else 0.0
            return [types.TextContent(
                type="text", 
                text=f"No commands found matching '{query}' with sufficient confidence. Best match score: {best_score:.3f} (threshold: {MIN_CONFIDENCE_SCORE})"
            )]
        
        # Format results for LLM consumption
        formatted_results = []
        for i, (record, score) in enumerate(filtered_results, 1):
            command_info = _format_command_result(record, score, is_validated and i == 1)
            formatted_results.append(f"{i}. {command_info}")
        
        response_text = f"Found {len(filtered_results)} matching commands:\n\n" + "\n\n".join(formatted_results)
        
        # Log performance info
        cache_status = "✅ VALIDATED" if is_validated else "🔍 COMPUTED"
        logger.info(f"{cache_status} query '{query}' -> {len(filtered_results)} results (filtered from {len(results)})")
        return [types.TextContent(type="text", text=response_text)]
        
    except Exception as e:
        logger.error(f"Error during semantic search: {e}")
        return [types.TextContent(
            type="text", 
            text=f"Error performing search: {str(e)}"
        )]

# Create SSE transport
sse = SseServerTransport("/messages")

async def handle_sse(request: Request):
    """Handle SSE connections."""
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0],
            streams[1],
            InitializationOptions(
                server_name="dynamic-cli-mcp-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
    return Response()

# Create Starlette app
app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages", app=sse.handle_post_message),
    ],
)

def find_config_file() -> Optional[Path]:
    """Find the config file in various standard locations."""
    import os
    
    # List of possible config locations (in order of preference)
    possible_paths = [
        # Project-specific config (highest priority)
        Path.cwd() / ".dynamic-cli" / "config.json",
        Path.cwd() / ".dynamic-cli" / "cli_config.json",
        
        # Current working directory
        Path.cwd() / "cli_config.json",
        Path.cwd() / "config" / "cli_config.json",
        
        # Environment variable
        Path(os.getenv("DYNAMIC_CLI_CONFIG", "")) if os.getenv("DYNAMIC_CLI_CONFIG") else None,
        
        # User home directory (fallback)
        Path.home() / ".config" / "dynamic-cli" / "config.json",
        Path.home() / ".dynamic-cli" / "config.json",
        
        # System-wide config (last resort)
        Path("/etc/dynamic-cli/config.json"),
    ]
    
    for config_path in possible_paths:
        if config_path and config_path.exists():
            return config_path
    
    return None

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Dynamic CLI MCP Server")
    parser.add_argument("--config", type=Path, help="Path to CLI configuration (auto-detected if not specified)")
    parser.add_argument("--host", default="localhost", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    
    args = parser.parse_args()
    
    # Auto-detect config if not provided
    config_path = args.config
    if not config_path:
        config_path = find_config_file()
        if not config_path:
            logger.error(
                "❌ No config file found. Please either:\n"
                "  • Create .dynamic-cli/config.json in current directory (project-specific)\n"
                "  • Create cli_config.json in current directory\n"
                "  • Use --config option to specify path explicitly"
            )
            return 1
        logger.info(f"📁 Auto-detected config: {config_path}")
    
    try:
        # Initialize server
        initialize_server(config_path)
        
        # Run the server
        logger.info(f"Starting Dynamic CLI MCP server on {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise

if __name__ == "__main__":
    main()