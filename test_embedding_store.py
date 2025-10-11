#!/usr/bin/env python3
"""Test script for EmbeddingStore functionality."""

import os
import tempfile
from pathlib import Path

# Use whatever embedding provider is configured (OpenAI if API key available, hash otherwise)
# Don't force hash embeddings - let the system decide based on API key availability

from src.dynamic_cli.config import CLIConfig
from src.dynamic_cli.embedding import EmbeddingStore, EmbeddingRecord


def test_embedding_store():
    """Test the EmbeddingStore with sample commands."""
    
    print("🧪 Testing EmbeddingStore functionality...")
    
    # Load the actual configuration
    config_path = Path("config/cli_config.json")
    if not config_path.exists():
        print("❌ Config file not found:", config_path)
        return False
    
    config = CLIConfig.load(config_path)
    print(f"✅ Loaded config with {len(config.commands)} commands")
    
    # Create temporary embedding store
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "test_embeddings.sqlite"
        store = EmbeddingStore.from_settings(config.mcp)
        store.path = temp_db  # Override path for testing
        store._initialize()
        
        # Detect which embedding provider is being used
        provider_type = type(store.provider).__name__
        if provider_type == "OpenAIEmbeddingProvider":
            print(f"✅ Using OpenAI embeddings (API key found)")
        else:
            print(f"✅ Using {provider_type} (no OpenAI API key)")
        
        print(f"✅ Created temporary embedding store at {temp_db}")
        
        # Build embedding records from config
        records = []
        for command in config.commands:
            for subcommand in command.subcommands:
                section_id = f"{command.name}.{subcommand.name}"
                
                # Create description from help text
                description = subcommand.help
                if subcommand.prepare_code:
                    # Extract comments from code as additional context
                    code_lines = subcommand.prepare_code.split('\n')
                    comments = [line.strip()[1:].strip() for line in code_lines if line.strip().startswith('#')]
                    if comments:
                        description += " " + " ".join(comments)
                
                # Create schema info for the record
                schema = create_command_schema(command.name, subcommand)
                
                records.append(
                    EmbeddingRecord(
                        section_id=section_id,
                        command=command.name,
                        subcommand=subcommand.name,
                        description=description,
                        schema=schema,
                    )
                )
        
        print(f"✅ Created {len(records)} embedding records")
        
        # Rebuild the embedding store
        store.rebuild(records)
        print("✅ Rebuilt embedding store with records")
        
        # Test queries based on actual commands in config
        test_cases = [
            # Test cases for storage.list command
            {
                "queries": [
                    "list storage objects",
                    "show files in bucket", 
                    "get bucket contents",
                    "list objects inside a bucket"
                ],
                "expected_command": "storage",
                "expected_subcommand": "list",
                "description": "Storage list command variations"
            },
            # Test cases for database.query command
            {
                "queries": [
                    "run sql query",
                    "execute database statement",
                    "run an SQL statement",
                    "supabase database operation"
                ],
                "expected_command": "database", 
                "expected_subcommand": "query",
                "description": "Database query command variations"
            },
            # Test cases for test.echo command
            {
                "queries": [
                    "echo message back",
                    "test echo command",
                    "echo back provided message",
                    "simple test command"
                ],
                "expected_command": "test",
                "expected_subcommand": "echo", 
                "description": "Test echo command variations"
            },
            # Test cases for jp.users command
            {
                "queries": [
                    "get list of users",
                    "load users from jsonplaceholder",
                    "fetch random users",
                    "get user data",
                    "show all users"
                ],
                "expected_command": "jp",
                "expected_subcommand": "users",
                "description": "JP users command variations"
            },
            # Negative test cases
            {
                "queries": [
                    "deploy kubernetes cluster",
                    "compile C++ program",
                    "send email notification",
                    "calculate fibonacci sequence"
                ],
                "expected_command": None,
                "expected_subcommand": None,
                "description": "Negative test cases (should have low scores)"
            }
        ]
        
        print("\n🔍 Running test queries...")
        
        all_passed = True
        for test_case in test_cases:
            print(f"\n📝 Testing: {test_case['description']}")
            
            for query in test_case["queries"]:
                print(f"  Query: '{query}'")
                
                try:
                    results = store.query(query, top_k=3)
                    
                    if not results:
                        if test_case["expected_command"] is None:
                            print("    ✅ No results (as expected for negative test)")
                        else:
                            print("    ❌ No results found")
                            all_passed = False
                        continue
                    
                    # Check top result
                    top_record, top_score = results[0]
                    print(f"    Top result: {top_record.command}.{top_record.subcommand} (score: {top_score:.3f})")
                    
                    if test_case["expected_command"] is None:
                        # Negative test - expect low scores  
                        CONFIDENCE_THRESHOLD = 0.4  # Should match server threshold
                        if top_score < CONFIDENCE_THRESHOLD:
                            print(f"    ✅ Low similarity score {top_score:.3f} (below threshold {CONFIDENCE_THRESHOLD})")
                        else:
                            print(f"    ⚠️  High similarity score {top_score:.3f} (above threshold {CONFIDENCE_THRESHOLD})")
                            all_passed = False
                    else:
                        # Positive test - expect correct command
                        if (top_record.command == test_case["expected_command"] and 
                            top_record.subcommand == test_case["expected_subcommand"]):
                            print("    ✅ Correct command found")
                        else:
                            print(f"    ❌ Expected {test_case['expected_command']}.{test_case['expected_subcommand']}, got {top_record.command}.{top_record.subcommand}")
                            all_passed = False
                    
                    # Show all results for context
                    print("    All results:")
                    for i, (record, score) in enumerate(results, 1):
                        print(f"      {i}. {record.command}.{record.subcommand} - {score:.3f}")
                        
                except Exception as e:
                    print(f"    ❌ Error: {e}")
                    all_passed = False
        
        # Test confidence threshold behavior
        print(f"\n🎯 Testing confidence threshold behavior...")
        CONFIDENCE_THRESHOLD = 0.4
        
        threshold_test_queries = [
            "compile C++ program",
            "send email notification", 
            "deploy kubernetes cluster"
        ]
        
        for query in threshold_test_queries:
            print(f"  Query: '{query}'")
            results = store.query(query, top_k=3)
            if results:
                top_record, top_score = results[0]
                print(f"    Best match: {top_record.command}.{top_record.subcommand} (score: {top_score:.3f})")
                
                # Apply same threshold logic as server
                if top_score >= CONFIDENCE_THRESHOLD:
                    print(f"    ⚠️  Would return result (score {top_score:.3f} >= {CONFIDENCE_THRESHOLD})")
                else:
                    print(f"    ✅ Would reject result (score {top_score:.3f} < {CONFIDENCE_THRESHOLD})")
        
        print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
        return all_passed


def create_command_schema(command_name: str, subcommand) -> dict:
    """Create schema information for a command."""
    
    # Build argument schema
    arguments = []
    for arg in subcommand.arguments:
        arg_info = {
            "name": arg.name,
            "help": arg.help,
            "type": arg.type,
            "required": arg.required,
            "param_type": arg.param_type,
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


if __name__ == "__main__":
    success = test_embedding_store()
    exit(0 if success else 1)