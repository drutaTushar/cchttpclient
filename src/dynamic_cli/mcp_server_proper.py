"""Proper MCP server implementation using official MCP Python SDK."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import typer
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from .config import CLIConfig
from .embedding import EmbeddingStore, EmbeddingRecord

# Set up logging to stderr (never stdout for MCP servers)
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("Dynamic CLI MCP Server")

# Global variables for server state
config: CLIConfig | None = None
store: EmbeddingStore | None = None


class SearchRequest(BaseModel):
    """Request model for semantic command search."""
    query: str
    limit: int = 3


def initialize_server(config_path: Path) -> None:
    """Initialize the MCP server with configuration."""
    global config, store
    
    logger.info(f"Initializing server with config: {config_path}")
    
    # Load configuration
    config = CLIConfig.load(config_path)
    
    # Set up embedding store
    store = EmbeddingStore.from_settings(config.mcp)
    
    # Build command index
    _build_command_index()
    
    logger.info("Server initialized successfully")


def _build_command_index() -> None:
    """Build the embedding index from available commands."""
    if not config or not store:
        return
        
    records: List[EmbeddingRecord] = []
    
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


def _create_command_schema(command_name: str, subcommand) -> Dict[str, Any]:
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


@mcp.tool()
def semantic_command_search(request: SearchRequest) -> str:
    """
    Search for CLI commands using semantic queries.
    
    This tool allows you to find CLI commands by describing what you want to do
    in natural language. It returns matching commands with their complete CLI
    syntax and argument schemas.
    
    Args:
        request: Search request containing the query and optional limit
    
    Returns:
        Formatted string with matching commands and their CLI syntax
    """
    if not store:
        return "Error: Server not initialized"
    
    query = request.query
    limit = min(request.limit, 10)  # Cap at 10 results
    
    logger.info(f"Searching for: {query} (limit: {limit})")
    
    try:
        # Perform semantic search
        results = store.query(query, top_k=limit)
        
        if not results:
            return f"No commands found matching: {query}"
        
        # Format results for LLM consumption
        formatted_results = []
        for i, (record, score) in enumerate(results, 1):
            command_info = _format_command_result(record, score)
            formatted_results.append(f"{i}. {command_info}")
        
        response_text = f"Found {len(results)} matching commands:\n\n" + "\n\n".join(formatted_results)
        
        logger.info(f"Returning {len(results)} results")
        return response_text
        
    except Exception as e:
        logger.error(f"Error during semantic search: {e}")
        return f"Error performing search: {str(e)}"


def _format_command_result(result: EmbeddingRecord, score: float) -> str:
    """Format a search result for LLM consumption."""
    
    schema = result.schema
    command_name = schema["command"]
    subcommand_name = schema["subcommand"]
    
    # Build CLI command template
    cli_parts = ["uv", "run", "-m", "dynamic_cli.cli", "--config", "config/cli_config.json", command_name, subcommand_name]
    
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

**Match Score**: {score:.3f}"""
    
    return result_text


def _get_example_value(arg: Dict[str, Any]) -> str:
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


# Main CLI application
def main(
    config: Path = typer.Option(..., help="Path to CLI configuration"),
    host: str = typer.Option("localhost", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
):
    """Run the MCP server with network transport."""
    
    try:
        # Initialize server
        initialize_server(config)
        
        # Run the MCP server
        logger.info(f"Starting MCP server on {host}:{port}")
        mcp.run(transport="sse")
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    typer.run(main)