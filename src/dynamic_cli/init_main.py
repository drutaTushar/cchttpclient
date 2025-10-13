#!/usr/bin/env python3
"""Project initialization entry point."""

import json
import os
import sys
from pathlib import Path


def main():
    """Main entry point for dynamic-cli-init that replicates the shell script functionality."""
    
    # Parse arguments
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("""
Dynamic CLI Project Initialization

Usage:
  dynamic-cli-init [PROJECT_DIR]

Arguments:
  PROJECT_DIR    Directory to initialize (default: current directory)

This command creates a .dynamic-cli/config.json file for project-specific
command configuration.
""")
        return
    
    # Get project directory (default to current directory)
    project_dir = Path.cwd() if len(sys.argv) <= 1 else Path(sys.argv[1])
    
    print(f"🚀 Initializing dynamic-cli project in: {project_dir}")
    
    # Create project directory if it doesn't exist
    if not project_dir.exists():
        print(f"📁 Creating project directory: {project_dir}")
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"❌ Failed to create directory: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Change to project directory
    original_cwd = Path.cwd()
    os.chdir(project_dir)
    
    try:
        # Create .dynamic-cli directory
        dynamic_cli_dir = Path(".dynamic-cli")
        if not dynamic_cli_dir.exists():
            print("📁 Creating .dynamic-cli directory")
            dynamic_cli_dir.mkdir()
        else:
            print("⚠️  .dynamic-cli directory already exists")
        
        # Create config file
        config_file = dynamic_cli_dir / "config.json"
        if not config_file.exists():
            print("📄 Creating basic config template")
            
            # Basic config template
            config_template = {
                "http_timeout": 30,
                "secrets": {},
                "commands": [
                    {
                        "name": "example",
                        "help": "Example commands for this project",
                        "subcommands": [
                            {
                                "name": "hello",
                                "help": "Say hello",
                                "prepare_code": "def prepare(request, helpers):\n    return None  # Skip HTTP request",
                                "response_code": "def process_response(response, helpers):\n    return {\"message\": \"Hello from your project!\"}",
                                "arguments": [],
                                "request": {
                                    "method": "GET",
                                    "url": "https://httpbin.org/get",
                                    "headers": {},
                                    "query": {},
                                    "body": {"mode": "json", "template": {}},
                                    "response": {"mode": "json", "success_codes": [200]}
                                }
                            }
                        ]
                    }
                ],
                "mcp": {
                    "embedding_model": "text-embedding-3-small",
                    "persist_path": "embeddings.sqlite",
                    "api_key_env": "OPENAI_API_KEY",
                    "api_base": None,
                    "collection_name": "command_descriptions",
                    "top_k": 3
                }
            }
            
            with open(config_file, 'w') as f:
                json.dump(config_template, f, indent=2)
            
            print("✅ Created basic .dynamic-cli/config.json")
        else:
            print("⚠️  .dynamic-cli/config.json already exists")
        
        # Update .gitignore
        gitignore_file = Path(".gitignore")
        gitignore_entry = ".dynamic-cli/embeddings.sqlite"
        
        if gitignore_file.exists():
            # Check if entry already exists
            gitignore_content = gitignore_file.read_text()
            if gitignore_entry not in gitignore_content:
                with open(gitignore_file, 'a') as f:
                    f.write(f"\n# Dynamic CLI\n{gitignore_entry}\n")
                print(f"✅ Added {gitignore_entry} to .gitignore")
        else:
            with open(gitignore_file, 'w') as f:
                f.write(f"# Dynamic CLI\n{gitignore_entry}\n")
            print(f"✅ Created .gitignore with dynamic-cli entries")
        
        print("")
        print("🎉 Project initialized successfully!")
        print("")
        print("Next steps:")
        print("  1. Edit .dynamic-cli/config.json to add your project-specific commands")
        print("  2. Test with: dynamic-cli example hello")
        print("  3. Add more commands and subcommands as needed")
        print("")
        print(f"Config location: {project_dir.resolve()}/.dynamic-cli/config.json")
        
    finally:
        # Restore original directory
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()