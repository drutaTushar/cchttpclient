"""Runtime helpers for executing request preparation scripts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import os
import subprocess

from .config import CLIConfig, SecretDefinition


class SecretNotFoundError(RuntimeError):
    pass


class ScriptExecutionError(RuntimeError):
    pass


@dataclass
class ScriptHelpers:
    """Helper functions exposed to user scripts."""

    config: CLIConfig

    def secret(self, name: str) -> str:
        definition = self.config.secrets.get(name)
        if not definition:
            raise SecretNotFoundError(f"Unknown secret '{name}'.")
        return _resolve_secret(definition)

    def env(self, key: str, default: Optional[str] = None) -> str:
        if key in os.environ:
            return os.environ[key]
        if default is not None:
            return default
        raise SecretNotFoundError(f"Environment variable '{key}' is not set.")

    def json(self, value: Any) -> str:
        return json.dumps(value)


@dataclass
class RequestScript:
    prepare: Callable[[Dict[str, Any]], Dict[str, Any]]
    process_response: Callable[[Any], Any]


def load_script(source: str, helpers: ScriptHelpers) -> RequestScript:
    """Compile the script source into callables."""

    namespace: Dict[str, Any] = {
        "json": json,
        "os": os,
    }

    try:
        exec(compile(source, "<script>", "exec"), namespace)
    except Exception as exc:  # pragma: no cover - defensive
        raise ScriptExecutionError(f"Failed to compile script: {exc}") from exc

    prepare = namespace.get("prepare")
    if not callable(prepare):
        raise ScriptExecutionError("Script must define a callable 'prepare(request, helpers)'.")

    process_response = namespace.get("process_response")
    if not callable(process_response):
        process_response = lambda response, _helpers: response

    def prepared(request: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return prepare(request, helpers)
        except Exception as exc:  # pragma: no cover - script failures propagated
            raise ScriptExecutionError(f"Error in prepare(): {exc}") from exc

    def processed(response: Any) -> Any:
        try:
            return process_response(response, helpers)
        except Exception as exc:  # pragma: no cover
            raise ScriptExecutionError(f"Error in process_response(): {exc}") from exc

    return RequestScript(prepare=prepared, process_response=processed)


def _resolve_secret(secret: SecretDefinition) -> str:
    if secret.type == "env":
        if not secret.env:
            raise SecretExecutionError("env secret requires 'env' field")
        value = os.getenv(secret.env)
        if value is None:
            raise SecretNotFoundError(f"Environment variable '{secret.env}' not set for secret '{secret.name}'.")
        return value
    if secret.type == "value":
        if secret.value is None:
            raise SecretExecutionError("value secret requires 'value' field")
        return secret.value
    if secret.type == "file":
        if not secret.path:
            raise SecretExecutionError("file secret requires 'path' field")
        file_path = Path(secret.path).expanduser()
        if not file_path.exists():
            raise SecretNotFoundError(f"Secret file '{file_path}' not found for '{secret.name}'.")
        return file_path.read_text(encoding=secret.encoding).strip()
    if secret.type == "command":
        if not secret.value:
            raise SecretExecutionError("command secret requires 'value' field with command")
        try:
            result = subprocess.run(
                secret.value,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - runtime
            raise SecretExecutionError(f"Secret command failed: {exc}") from exc
        return result.stdout.strip()

    raise SecretExecutionError(f"Unsupported secret type '{secret.type}'.")


class SecretExecutionError(RuntimeError):
    pass
