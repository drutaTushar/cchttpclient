"""Runtime helpers for executing request preparation scripts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import os
import subprocess
import sys
import threading

from .config import CLIConfig, SecretDefinition


class SecretNotFoundError(RuntimeError):
    pass


class ScriptExecutionError(RuntimeError):
    pass


class StateManager:
    """Manages persistent state storage for CLI commands."""
    
    def __init__(self, state_file_path: Path):
        self.state_file_path = state_file_path
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None
    
    def _load_state(self) -> Dict[str, Any]:
        """Load state from file or return empty dict if file doesn't exist."""
        if not self.state_file_path.exists():
            return {}
        
        try:
            with open(self.state_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # If file is corrupted or unreadable, start fresh
            return {}
    
    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save state to file."""
        # Ensure the directory exists
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.state_file_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            raise ScriptExecutionError(f"Failed to save state: {e}")
    
    def get(self, key: str, default=None) -> Any:
        """Get a value from state."""
        with self._lock:
            if self._cache is None:
                self._cache = self._load_state()
            return self._cache.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in state and save to file."""
        with self._lock:
            if self._cache is None:
                self._cache = self._load_state()
            self._cache[key] = value
            self._save_state(self._cache)
    
    def delete(self, key: str) -> bool:
        """Delete a key from state. Returns True if key existed."""
        with self._lock:
            if self._cache is None:
                self._cache = self._load_state()
            if key in self._cache:
                del self._cache[key]
                self._save_state(self._cache)
                return True
            return False
    
    def clear(self) -> None:
        """Clear all state."""
        with self._lock:
            self._cache = {}
            self._save_state(self._cache)
    
    def list_keys(self) -> list[str]:
        """Get all state keys."""
        with self._lock:
            if self._cache is None:
                self._cache = self._load_state()
            return list(self._cache.keys())
    
    def get_all(self) -> Dict[str, Any]:
        """Get all state data."""
        with self._lock:
            if self._cache is None:
                self._cache = self._load_state()
            return self._cache.copy()


@dataclass
class ScriptHelpers:
    """Helper functions exposed to user scripts."""

    config: CLIConfig
    state_manager: Optional[StateManager] = None

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

    def json(self, value: Any) -> Any:
        """Parse JSON if string, otherwise return as-is for serialization."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        elif isinstance(value, (dict, list)):
            # If it's already parsed, return as-is
            return value
        else:
            # For other types, try to serialize
            return json.dumps(value)
    
    def dumps(self, value: Any) -> str:
        """Serialize value to JSON string."""
        return json.dumps(value, indent=2)
    
    def loads(self, value: str) -> Any:
        """Parse JSON string to Python object."""
        return json.loads(value)
    
    def get(self, data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Safely get value from dictionary."""
        return data.get(key, default)
    
    def filter(self, items: List[Dict[str, Any]], key: str, value: Any) -> List[Dict[str, Any]]:
        """Filter list of dictionaries by key-value pair."""
        return [item for item in items if item.get(key) == value]
    
    def map(self, items: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
        """Extract only specified keys from list of dictionaries."""
        return [{k: item.get(k) for k in keys} for item in items]
    
    def state_get(self, key: str, default=None) -> Any:
        """Get a value from persistent state."""
        if self.state_manager is None:
            raise ScriptExecutionError("State management not initialized")
        return self.state_manager.get(key, default)
    
    def state_set(self, key: str, value: Any) -> None:
        """Set a value in persistent state."""
        if self.state_manager is None:
            raise ScriptExecutionError("State management not initialized")
        self.state_manager.set(key, value)
    
    def state_delete(self, key: str) -> bool:
        """Delete a key from persistent state. Returns True if key existed."""
        if self.state_manager is None:
            raise ScriptExecutionError("State management not initialized")
        return self.state_manager.delete(key)
    
    def state_clear(self) -> None:
        """Clear all persistent state."""
        if self.state_manager is None:
            raise ScriptExecutionError("State management not initialized")
        self.state_manager.clear()

    def log(self, *args, **kwargs) -> None:
        """Print informational message to stdout (default color)."""
        print(*args, **kwargs, file=sys.stdout)

    def warn(self, *args, **kwargs) -> None:
        """Print warning message to stderr in yellow."""
        message = " ".join(str(arg) for arg in args)
        print(f"\033[93m{message}\033[0m", **kwargs, file=sys.stderr)

    def error(self, *args, **kwargs) -> None:
        """Print error message to stderr in red."""
        message = " ".join(str(arg) for arg in args)
        print(f"\033[91m{message}\033[0m", **kwargs, file=sys.stderr)


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


def load_script_from_code(prepare_code: str, response_code: str, helpers: ScriptHelpers) -> RequestScript:
    """Load script from separate prepare and response code strings."""
    
    # Combine the code into a single script
    combined_code = f"{prepare_code}\n\n{response_code}"
    
    return load_script(combined_code, helpers)


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
