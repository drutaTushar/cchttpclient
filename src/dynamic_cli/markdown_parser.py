"""Utilities for reading Markdown command definitions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import re

import yaml


CODE_BLOCK_RE = re.compile(
    r"```(?P<lang>\w+)?\n(?P<code>.*?)(?:```)", re.DOTALL
)


@dataclass
class MarkdownSection:
    identifier: str
    command: str
    subcommand: str
    description: str
    script: str
    metadata: Dict[str, str]


class MarkdownParserError(RuntimeError):
    """Raised when the Markdown file is invalid."""


def parse_markdown_sections(path: Path) -> Dict[str, MarkdownSection]:
    """Parse the Markdown file into sections keyed by identifier."""

    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    index = 0
    sections: Dict[str, MarkdownSection] = {}

    while index < len(lines):
        # Seek to the next section start
        while index < len(lines) and lines[index].strip() != "---":
            index += 1
        if index >= len(lines):
            break
        index += 1  # skip '---'

        yaml_lines: List[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            yaml_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise MarkdownParserError("Missing content delimiter '---' after YAML metadata.")
        index += 1  # skip '---' between metadata and body

        body_lines: List[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            body_lines.append(lines[index])
            index += 1

        raw_yaml = "\n".join(yaml_lines)
        body = "\n".join(body_lines)
        meta = yaml.safe_load(raw_yaml) or {}

        identifier = meta.get("id")
        command = meta.get("command")
        subcommand = meta.get("subcommand")
        if not identifier or not command or not subcommand:
            raise MarkdownParserError(
                "Section metadata must provide 'id', 'command', and 'subcommand'."
            )

        code_match = CODE_BLOCK_RE.search(body)
        script = code_match.group("code").strip() if code_match else ""
        description = CODE_BLOCK_RE.sub("", body).strip()

        sections[identifier] = MarkdownSection(
            identifier=identifier,
            command=command,
            subcommand=subcommand,
            description=description,
            script=script,
            metadata=meta,
        )

        # Skip trailing separator if present
        if index < len(lines) and lines[index].strip() == "---":
            index += 1

    return sections
