"""Dynamic CLI entry point."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

import httpx
import typer

from .config import ArgumentDefinition, CLIConfig, SubcommandDefinition
from .markdown_parser import parse_markdown_sections
from .scripting import RequestScript, ScriptHelpers, load_script


TYPE_MAP: Dict[str, Callable[[Any], Any]] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "json": lambda value: json.loads(value) if isinstance(value, str) else value,
}


def _annotation_for_type(type_name: str):
    if type_name == "json":
        return str
    return TYPE_MAP.get(type_name, str)


class CommandRuntime:
    def __init__(self, config: CLIConfig):
        self.config = config
        self.sections = parse_markdown_sections(config.markdown_path)
        self.script_cache: Dict[str, RequestScript] = {}

    def get_script(self, section_id: str) -> RequestScript:
        if section_id in self.script_cache:
            return self.script_cache[section_id]
        section = self.sections.get(section_id)
        if not section:
            raise typer.BadParameter(f"Unknown script section '{section_id}'.")
        helpers = ScriptHelpers(config=self.config)
        script = load_script(section.script, helpers)
        self.script_cache[section_id] = script
        return script


def _prepare_parameter(argument: ArgumentDefinition):
    annotation = _annotation_for_type(argument.type)
    cli_name = argument.cli_name or (
        f"--{argument.name.replace('_', '-')}" if argument.param_type == "option" else argument.name
    )
    param_decls = [cli_name, *argument.aliases] if argument.param_type == "option" else [argument.name]

    if argument.param_type == "argument":
        default = argument.default
        if argument.required and default is None:
            default = ...
        default_value = typer.Argument(
            default,
            help=argument.help,
        )
        param_kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
    else:
        default_value = typer.Option(
            argument.default if argument.default is not None else (... if argument.required else None),
            *param_decls,
            help=argument.help,
            show_default=argument.default is not None,
        )
        param_kind = inspect.Parameter.KEYWORD_ONLY

    return inspect.Parameter(
        argument.name,
        param_kind,
        default=default_value,
        annotation=annotation,
    )


def _build_request_payload(subcommand: SubcommandDefinition, values: Dict[str, Any]) -> Dict[str, Any]:
    request = subcommand.request
    headers = dict(request.headers)
    params = dict(request.query)
    json_body: Dict[str, Any] = dict(request.body.template)
    path_params: Dict[str, Any] = {}

    for argument in subcommand.arguments:
        value = values.get(argument.name)
        if value is None:
            continue
        if argument.type == "json" and value is not None:
            value = TYPE_MAP["json"](value)
        target_key = argument.target or argument.name
        location = argument.location
        if location == "header":
            headers[target_key] = value
        elif location == "query":
            params[target_key] = value
        elif location == "path":
            path_params[target_key] = value
        else:
            json_body[target_key] = value

    url = request.url.format(**path_params)

    payload: Dict[str, Any] = {
        "method": request.method,
        "url": url,
        "headers": headers,
        "params": params,
        "json": json_body if request.body.mode == "json" else None,
        "data": json_body if request.body.mode != "json" else None,
        "timeout": request.timeout,
    }
    return payload


def _create_handler(runtime: CommandRuntime, subcommand: SubcommandDefinition):
    def handler(**kwargs):
        request_payload = _build_request_payload(subcommand, kwargs)
        script = runtime.get_script(subcommand.script_section)
        prepared = script.prepare(request_payload)

        # If prepare returns None, skip HTTP request (for test commands)
        if prepared is None:
            result_data = None
        else:
            timeout = prepared.get("timeout") or request_payload.get("timeout") or runtime.config.http_timeout
            request_args = {
                "method": prepared.get("method", request_payload.get("method")),
                "url": prepared.get("url", request_payload.get("url")),
                "headers": prepared.get("headers", request_payload.get("headers")),
                "params": prepared.get("params", request_payload.get("params")),
                "json": prepared.get("json", request_payload.get("json")),
                "data": prepared.get("data", request_payload.get("data")),
            }

            with httpx.Client(timeout=timeout) as client:
                response = client.request(**request_args)
            response.raise_for_status()

            if subcommand.request.response.mode == "json":
                result_data = response.json()
            else:
                result_data = response.text

        processed = script.process_response(result_data)
        typer.echo(json.dumps(processed, indent=2) if isinstance(processed, (dict, list)) else processed)

    parameters = [_prepare_parameter(arg) for arg in subcommand.arguments]
    handler.__signature__ = inspect.Signature(parameters)
    handler.__name__ = subcommand.name
    return handler


def create_app(config_path: Path) -> typer.Typer:
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    root_app = typer.Typer(help="Dynamic HTTP client")

    for command in config.commands:
        command_app = typer.Typer(help=command.help)
        for subcommand in command.subcommands:
            handler = _create_handler(runtime, subcommand)
            command_app.command(subcommand.name)(handler)
        root_app.add_typer(command_app, name=command.name)

    @root_app.callback()
    def _callback():
        """Shared CLI callback for initialization."""
        return None

    return root_app


def _extract_config_path(argv: Sequence[str]) -> tuple[Path, List[str]]:
    args = list(argv)
    if "--config" in args:
        index = args.index("--config")
    elif "-c" in args:
        index = args.index("-c")
    else:
        raise typer.BadParameter("Missing required --config option.")

    try:
        config_value = args[index + 1]
    except IndexError as exc:  # pragma: no cover - CLI misuse
        raise typer.BadParameter("--config option requires a path argument") from exc

    remainder = args[:index] + args[index + 2 :]
    return Path(config_value), remainder


def main(argv: Sequence[str] | None = None):
    argv = list(argv or sys.argv[1:])
    try:
        config_path, remainder = _extract_config_path(argv)
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from exc

    app = create_app(config_path)

    if not remainder and ("-h" in argv or "--help" in argv):
        remainder = ["--help"]

    app(prog_name="dynamic-cli", args=remainder)


if __name__ == "__main__":
    main()
