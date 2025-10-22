Perfect! I've successfully implemented file import support with the @filename syntax. Here's what was done:

  Implementation Summary

  1. File Import Logic (src/dynamic_cli/cli.py:94-109)

  Added support for curl-style @filename syntax in _build_request_payload:
  - Detects @ prefix in any string argument value
  - Reads file content before type conversion and prepare handler execution
  - Resolves relative paths from current working directory
  - Works with all argument types (json, str, int, etc.) and locations (body, header, query, path)

  2. Error Handling

  - Clear error message when file doesn't exist: "Error: File not found: {filepath}"
  - Graceful handling of file read errors with exception details
  - Exits with code 1 on file errors

  3. Comprehensive Tests

  Added 5 new test cases in tests/test_cli_integration.py:
  - ✅ test_file_import_with_at_syntax - Basic JSON file import
  - ✅ test_file_import_with_relative_path - Relative path resolution
  - ✅ test_file_import_string_value_in_header - String files in headers
  - ✅ test_file_import_missing_file_error - Error handling
  - ✅ test_file_import_with_multiline_content - Multiline/pretty-printed JSON

  Usage Examples

  # JSON body from file
  dynamic-cli api create-user @user.json

  # Token from file in header
  dynamic-cli api call --token @token.txt @payload.json

  # Relative path
  dynamic-cli api submit @./data/request.json

  # Works with prepare handlers - they receive the actual content
  # The prepare handler gets the parsed data, not the filename

  Key Design Decisions

  1. File reading happens BEFORE prepare handler - The prepare handler receives actual content, not filenames, giving it full control
  2. Type conversion after file read - JSON files get automatically parsed if argument type is "json"
  3. No stripping - File content is preserved exactly as-is (matching curl behavior)
  4. Works anywhere - Any argument (body, header, query, path) can use @filename

  Bonus Fix

  Also fixed a pre-existing test failure in test_cli_invokes_configured_request by updating the test config to use the current prepare_code/response_code format instead of the obsolete script_section
  approach.

  All 6 tests now pass! ✅

---

Version Bump & Installation

  1. Version Bumped

  - Changed from 0.2.1 → 0.3.0 in pyproject.toml:3
  - This is a minor version bump indicating new feature (file import support)

  2. System-wide Installation

  - Synced uv lock file with new version
  - Reinstalled using uv tool install . --force
  - Successfully installed version 0.3.0 globally

  3. Verification

  $ uv tool list | grep dynamic-cli
  dynamic-cli v0.3.0
  - dynamic-cli
  - dynamic-cli-admin
  - dynamic-cli-init
  - dynamic-cli-mcp

  $ which dynamic-cli
  /home/tushar/.local/bin/dynamic-cli

  All 4 executables are now available system-wide with version 0.3.0, which includes the new @filename file import feature!

  You can now use the file import feature anywhere:
  # Example usage
  dynamic-cli jp users @user_payload.json
  dynamic-cli api call --token @token.txt @request.json
