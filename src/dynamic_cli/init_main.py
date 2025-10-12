#!/usr/bin/env python3
"""Project initialization entry point."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Main entry point for dynamic-cli-init."""
    
    # Get the project root directory
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent
    init_script = project_root / "bin" / "dynamic-cli-init"
    
    if not init_script.exists():
        print(f"❌ Init script not found at: {init_script}", file=sys.stderr)
        sys.exit(1)
    
    # Execute the shell script with all arguments
    try:
        result = subprocess.run([str(init_script)] + sys.argv[1:], check=False)
        sys.exit(result.returncode)
    except Exception as e:
        print(f"❌ Error running init script: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()