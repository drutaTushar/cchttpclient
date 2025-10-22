"""Integration tests for the dynamic CLI against a mock HTTP server."""
from __future__ import annotations

import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict
import types

import pytest

# Ensure the src directory is importable without installing the package.
import sys

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

try:  # pragma: no cover - prefer the real library when available
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - simplified stub for tests
    import http.client
    from urllib.parse import urlencode, urlsplit

    httpx = types.ModuleType("httpx")
    json_module = json

    class _Response:
        def __init__(self, status_code: int, body: bytes, headers: Dict[str, str]):
            self.status_code = status_code
            self._body = body
            self._headers = headers

        def raise_for_status(self):
            if not (200 <= self.status_code < 300):
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return json.loads(self._body.decode("utf-8"))

        @property
        def text(self):
            return self._body.decode("utf-8")

    class _Client:
        def __init__(self, timeout: float | None = None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method: str, url: str, headers=None, params=None, json=None, data=None):
            headers = dict(headers or {})
            params = params or {}

            _scheme, netloc, path, query, _fragment = urlsplit(url)
            if params:
                query = urlencode(params)
            path = path or "/"
            if query:
                path = f"{path}?{query}"

            body_bytes: bytes | None = None
            if json is not None:
                body_bytes = json_module.dumps(json).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            elif data is not None:
                if isinstance(data, (bytes, bytearray)):
                    body_bytes = bytes(data)
                elif isinstance(data, str):
                    body_bytes = data.encode("utf-8")
                else:
                    body_bytes = json_module.dumps(data).encode("utf-8")

            connection = http.client.HTTPConnection(netloc)
            connection.request(method, path, body=body_bytes, headers=headers)
            response = connection.getresponse()
            body = response.read()
            header_map = {k: v for k, v in response.getheaders()}
            connection.close()
            return _Response(response.status, body, header_map)

    httpx.Client = _Client  # type: ignore[attr-defined]
    sys.modules["httpx"] = httpx

try:  # pragma: no cover - prefer PyYAML when available
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - simple YAML loader for tests
    yaml = types.ModuleType("yaml")

    def _safe_load(text: str):
        data: Dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip("'\"")
        return data

    yaml.safe_load = _safe_load  # type: ignore[attr-defined]
    sys.modules["yaml"] = yaml

try:  # pragma: no cover - exercised when Typer is available
    import typer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for offline test environments
    import types

    typer = types.ModuleType("typer")

    class _BadParameter(Exception):
        pass

    class _Exit(Exception):
        def __init__(self, code: int = 0):
            self.exit_code = code

    def _argument(default, *_, **__):
        return default

    def _option(default, *_, **__):
        return default

    class _Typer:
        def __init__(self, *_, **__):
            pass

        def command(self, _name: str):
            def decorator(func):
                return func

            return decorator

        def add_typer(self, _app, _name: str):
            return None

        def callback(self):
            def decorator(func):
                return func

            return decorator

    def _echo(value):
        print(value)

    typer.BadParameter = _BadParameter  # type: ignore[attr-defined]
    typer.Exit = _Exit  # type: ignore[attr-defined]
    typer.Argument = _argument  # type: ignore[attr-defined]
    typer.Option = _option  # type: ignore[attr-defined]
    typer.Typer = _Typer  # type: ignore[attr-defined]
    typer.echo = _echo  # type: ignore[attr-defined]
    sys.modules["typer"] = typer

from dynamic_cli.cli import CommandRuntime, _create_handler
from dynamic_cli.config import CLIConfig


class _RecordingHandler(BaseHTTPRequestHandler):
    """A request handler that records incoming requests for assertions."""

    received: Dict[str, object] = {}
    response_payload: Dict[str, object] = {"status": "ok", "payload": {"value": 42}}

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else ""

        _RecordingHandler.received = {
            "path": self.path,
            "headers": {key: value for key, value in self.headers.items()},
            "body": body,
        }

        response_body = json.dumps(self.response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args):  # noqa: A003 - required signature
        """Silence the default HTTP server logging during tests."""


@pytest.fixture()
def mock_server():
    """Start a background HTTP server for the duration of the test."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _write_test_files(tmp_path: Path, server_port: int) -> Path:
    markdown = (
        "---\n"
        "id: mock_call\n"
        "command: mock\n"
        "subcommand: call\n"
        "---\n"
        "Test command.\n\n"
        "```python\n"
        "def prepare(request, helpers):\n"
        "    request['headers']['X-Auth'] = f\"Bearer {helpers.secret('api_key')}\"\n"
        "    request['json']['payload']['injected'] = True\n"
        "    request['json']['meta'] = {'port': request['url'].split(':')[-1]}\n"
        "    return request\n\n"
        "def process_response(response, helpers):\n"
        "    response['processed'] = True\n"
        "    return response\n"
        "```\n"
        "---\n"
    )

    markdown_path = tmp_path / "commands.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    config = {
        "markdown_path": str(markdown_path),
        "http_timeout": 5,
        "secrets": {
            "api_key": {
                "type": "value",
                "value": "test-secret",
            }
        },
        "commands": [
            {
                "name": "mock",
                "help": "",
                "subcommands": [
                    {
                        "name": "call",
                        "help": "",
                        "prepare_code": (
                            "def prepare(request, helpers):\n"
                            "    request['headers']['X-Auth'] = f\"Bearer {helpers.secret('api_key')}\"\n"
                            "    request['json']['payload']['injected'] = True\n"
                            "    request['json']['meta'] = {'port': request['url'].split(':')[-1]}\n"
                            "    return request"
                        ),
                        "response_code": (
                            "def process_response(response, helpers):\n"
                            "    response['processed'] = True\n"
                            "    return response"
                        ),
                        "arguments": [
                            {
                                "name": "payload",
                                "help": "Payload JSON",
                                "type": "json",
                                "required": True,
                                "location": "json",
                            },
                            {
                                "name": "user_token",
                                "help": "Additional header",
                                "param_type": "option",
                                "cli_name": "--user-token",
                                "location": "header",
                                "required": True,
                                "target": "X-User",
                            },
                        ],
                        "request": {
                            "method": "POST",
                            "url": f"http://127.0.0.1:{server_port}/api/run",
                            "headers": {
                                "Content-Type": "application/json",
                            },
                            "query": {},
                            "body": {
                                "mode": "json",
                                "template": {
                                    "payload": {},
                                    "base": True,
                                },
                            },
                            "response": {
                                "mode": "json",
                            },
                            "timeout": 2,
                        },
                    }
                ],
            }
        ],
        "mcp": {
            "embedding_model": "text-embedding-3-small",
            "persist_path": str(tmp_path / "embeddings.db"),
            "api_key_env": "OPENAI_API_KEY",
            "api_base": None,
            "collection_name": "test",
            "top_k": 1,
        },
    }

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_cli_invokes_configured_request(mock_server, tmp_path):
    """The CLI should send a request with enriched headers and body."""

    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    payload = json.dumps({"foo": "bar"})

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        handler(payload=payload, user_token="external")

    output = stdout.getvalue().strip()
    response_data = json.loads(output)
    assert response_data["status"] == "ok"
    assert response_data["processed"] is True

    recorded = _RecordingHandler.received
    assert recorded["path"] == "/api/run"

    headers: Dict[str, str] = recorded["headers"]  # type: ignore[assignment]
    assert headers["X-Auth"] == "Bearer test-secret"
    assert headers["X-User"] == "external"
    assert headers["Content-Type"].startswith("application/json")

    body = json.loads(recorded["body"])
    assert body["base"] is True
    assert body["payload"]["foo"] == "bar"
    assert body["payload"]["injected"] is True
    assert str(mock_server.server_address[1]) in body["meta"]["port"]


def test_file_import_with_at_syntax(mock_server, tmp_path):
    """Test that @filename syntax reads file content correctly."""

    # Create a test JSON file
    test_data = {"name": "Alice", "email": "alice@example.com"}
    json_file = tmp_path / "test_payload.json"
    json_file.write_text(json.dumps(test_data), encoding="utf-8")

    # Create config with command that uses the file
    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    # Use @filename syntax
    with contextlib.redirect_stdout(io.StringIO()):
        handler(payload=f"@{json_file}", user_token="external")

    # Verify the file content was read and sent
    recorded = _RecordingHandler.received
    body = json.loads(recorded["body"])
    assert body["payload"]["name"] == "Alice"
    assert body["payload"]["email"] == "alice@example.com"


def test_file_import_with_relative_path(mock_server, tmp_path, monkeypatch):
    """Test that relative paths are resolved correctly."""

    # Change to tmp_path directory
    monkeypatch.chdir(tmp_path)

    # Create a test JSON file in current directory
    test_data = {"status": "active"}
    json_file = tmp_path / "relative_payload.json"
    json_file.write_text(json.dumps(test_data), encoding="utf-8")

    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    # Use relative path
    with contextlib.redirect_stdout(io.StringIO()):
        handler(payload="@relative_payload.json", user_token="external")

    recorded = _RecordingHandler.received
    body = json.loads(recorded["body"])
    assert body["payload"]["status"] == "active"


def test_file_import_string_value_in_header(mock_server, tmp_path):
    """Test that file import works for string values in headers."""

    # Create a test token file
    token_file = tmp_path / "token.txt"
    token_file.write_text("secret-token-12345", encoding="utf-8")

    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    # Use @filename for header value
    with contextlib.redirect_stdout(io.StringIO()):
        handler(payload='{"test": "data"}', user_token=f"@{token_file}")

    recorded = _RecordingHandler.received
    headers: Dict[str, str] = recorded["headers"]  # type: ignore[assignment]
    assert headers["X-User"] == "secret-token-12345"


def test_file_import_missing_file_error(mock_server, tmp_path):
    """Test that missing file produces a clear error message."""

    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    # Try to use a non-existent file
    with contextlib.redirect_stdout(io.StringIO()) as stdout, \
         contextlib.redirect_stderr(io.StringIO()) as stderr:
        try:
            handler(payload="@nonexistent.json", user_token="external")
        except SystemExit as e:
            assert e.code == 1
            error_output = stderr.getvalue()
            assert "File not found" in error_output
            assert "nonexistent.json" in error_output
        else:
            raise AssertionError("Expected SystemExit but handler succeeded")


def test_file_import_with_multiline_content(mock_server, tmp_path):
    """Test that multiline file content is handled correctly."""

    # Create a file with multiline JSON (pretty-printed)
    test_data = {
        "users": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]
    }
    json_file = tmp_path / "multiline.json"
    json_file.write_text(json.dumps(test_data, indent=2), encoding="utf-8")

    config_path = _write_test_files(tmp_path, mock_server.server_address[1])
    config = CLIConfig.load(config_path)
    runtime = CommandRuntime(config)
    subcommand = config.commands[0].subcommands[0]
    handler = _create_handler(runtime, subcommand)

    with contextlib.redirect_stdout(io.StringIO()):
        handler(payload=f"@{json_file}", user_token="external")

    recorded = _RecordingHandler.received
    body = json.loads(recorded["body"])
    assert len(body["payload"]["users"]) == 2
    assert body["payload"]["users"][0]["name"] == "Alice"
    assert body["payload"]["users"][1]["name"] == "Bob"
