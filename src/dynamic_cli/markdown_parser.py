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
    sections: Dict[str, MarkdownSection] = {}
    
    # Split by section delimiters (lines with just ---)
    raw_sections = []
    current_section = []
    
    for line in text.splitlines():
        if line.strip() == "---":
            if current_section:
                raw_sections.append(current_section)
                current_section = []
        else:
            current_section.append(line)
    
    # Add final section if exists
    if current_section:
        raw_sections.append(current_section)
    
    # Process sections in pairs (metadata, content)
    for i in range(0, len(raw_sections), 2):
        if i + 1 >= len(raw_sections):
            break  # Need both metadata and content
            
        yaml_lines = raw_sections[i]
        body_lines = raw_sections[i + 1]
        
        raw_yaml = "\n".join(yaml_lines)
        body = "\n".join(body_lines)
        
        try:
            meta = yaml.safe_load(raw_yaml) or {}
        except yaml.YAMLError as e:
            raise MarkdownParserError(f"Invalid YAML metadata: {e}")

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

    return sections
