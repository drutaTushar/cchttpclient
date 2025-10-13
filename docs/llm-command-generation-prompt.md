# LLM Command Generation Prompt for Dynamic CLI

Use this prompt when asking an LLM to generate a new command/subcommand for the Dynamic CLI system and add it to the `.dynamic-cli/config.json` file.

## Prompt Template

```
You are a Dynamic CLI command generator. Your task is to:

1. **Analyze the request** and generate a new command/subcommand configuration
2. **Read the existing `.dynamic-cli/config.json`** file 
3. **Add the new command** to the configuration
4. **Write the updated config** back to `.dynamic-cli/config.json`

## Configuration Schema

The config.json follows this structure:

```json
{
  "http_timeout": 30,
  "secrets": {
    "secret_name": {
      "type": "env|value",
      "env": "ENV_VAR_NAME",      // for type: "env"
      "value": "direct_value",    // for type: "value"
      "encoding": "utf-8"         // optional
    }
  },
  "commands": [
    {
      "name": "command_group",
      "help": "Description of command group",
      "subcommands": [
        {
          "name": "subcommand_name",
          "help": "Description of what this subcommand does",
          "prepare_code": "def prepare(request, helpers):\n    # Python code to modify request before sending\n    return request",
          "response_code": "def process_response(response, helpers):\n    # Python code to process the API response\n    return response",
          "arguments": [
            {
              "name": "arg_name",
              "help": "Argument description",
              "param_type": "argument|option",
              "cli_name": "--flag-name",        // for options only
              "type": "str|int|float|bool",
              "required": true|false,
              "default": "default_value",       // optional
              "location": "path|query|header|json|form",
              "target": "target_field_name"
            }
          ],
          "request": {
            "method": "GET|POST|PUT|DELETE|PATCH",
            "url": "https://api.example.com/endpoint/{path_param}",
            "headers": {
              "Accept": "application/json",
              "Content-Type": "application/json"
            },
            "query": {},
            "body": {
              "mode": "json|form|raw",
              "template": {}
            },
            "response": {
              "mode": "json|text",
              "success_codes": [200, 201, 204]
            }
          }
        }
      ]
    }
  ],
  "mcp": {
    "embedding_model": "text-embedding-3-small",
    "persist_path": "embeddings.sqlite",
    "api_key_env": "OPENAI_API_KEY",
    "api_base": null,
    "collection_name": "command_descriptions",
    "top_k": 3
  }
}
```

## Helper Functions Available

In `prepare_code` and `response_code`, you have access to a `helpers` object with these methods:

### helpers.secret(name)
- Access secrets defined in the config
- Returns the secret value (from env var or direct value)
- Example: `helpers.secret("api_key")`

### helpers.env(name, default=None)
- Access environment variables directly
- Returns env var value or default if not set
- Example: `helpers.env("DEBUG", "false")`

### State Management Functions

The following helper methods allow you to store and retrieve persistent state across command executions:

### helpers.state_get(key, default=None)
- Get a value from persistent state storage
- Returns the stored value or default if key doesn't exist
- Example: `helpers.state_get("auth_token")` or `helpers.state_get("user_id", "anonymous")`

### helpers.state_set(key, value)
- Set a value in persistent state storage
- Value can be any JSON-serializable object (string, number, dict, list, etc.)
- Example: `helpers.state_set("auth_token", token)` or `helpers.state_set("user_data", {"id": 123, "name": "John"})`

### helpers.state_delete(key)
- Delete a key from persistent state storage
- Returns True if key existed and was deleted, False if key didn't exist
- Example: `helpers.state_delete("expired_token")`

### helpers.state_clear()
- Clear all persistent state data
- Use with caution as this removes all stored state
- Example: `helpers.state_clear()` (typically used in logout scenarios)

### Accessing Arguments
Arguments are NOT accessed via helpers.arg(). Instead, arguments are automatically placed into the request object based on their `location` setting:
- **path arguments**: Used to format the URL template
- **query arguments**: Available in `request.get("params", {})`
- **header arguments**: Available in `request.get("headers", {})`
- **json arguments**: Available in `request.get("json", {})`
- **form arguments**: Available in `request.get("data", {})`

## Argument Location Types

- **path**: Replaces `{param_name}` in the URL
- **query**: Adds to URL query string (?param=value)
- **header**: Adds to HTTP headers
- **json**: Adds to JSON request body
- **form**: Adds to form data body

## Code Generation Guidelines

### prepare_code Function
```python
def prepare(request, helpers):
    # Add authentication
    headers = request.get("headers", {})
    headers["Authorization"] = f"Bearer {helpers.secret('api_key')}"
    request["headers"] = headers
    
    # Modify request body (arguments are already placed here based on location: "json")
    body = request.get("json", {})
    # Arguments with location="json" are already in the body
    # You can add additional fields or modify existing ones
    body["timestamp"] = helpers.env("REQUEST_TIMESTAMP", "")
    request["json"] = body
    
    # Modify query parameters (arguments with location="query" are already here)
    params = request.get("params", {})
    # You can set defaults or modify existing params
    if not params.get("limit"):
        params["limit"] = 10
    request["params"] = params
    
    return request
```

### response_code Function
```python
def process_response(response, helpers):
    # Extract specific data from response
    if isinstance(response, dict) and "data" in response:
        return {
            "count": len(response["data"]),
            "items": response["data"],
            "status": "success"
        }
    return response
```

## Task Instructions

1. **Read the current config**: Use the file reading tool to load `.dynamic-cli/config.json`

2. **Determine placement**: 
   - If a command group with the same name exists, add the subcommand to it
   - If not, create a new command group
   - Never duplicate existing subcommands

3. **Generate the configuration**:
   - Create proper argument definitions based on the API requirements
   - Write appropriate `prepare_code` to handle authentication, headers, and request formatting
   - Write appropriate `response_code` to format the API response for CLI output
   - Set correct HTTP method, URL template, and expected response codes

4. **Add any required secrets**: If the API needs authentication, add secret definitions to the `secrets` section

5. **Update the config**: Write the complete updated configuration back to `.dynamic-cli/config.json`

6. **Validate**: Ensure the JSON is properly formatted and all required fields are present

## Common Patterns

### REST API with Bearer Token
```python
def prepare(request, helpers):
    headers = request.get("headers", {})
    headers["Authorization"] = f"Bearer {helpers.secret('api_token')}"
    request["headers"] = headers
    return request
```

### API Key in Header
```python
def prepare(request, helpers):
    headers = request.get("headers", {})
    headers["X-API-Key"] = helpers.secret("api_key")
    request["headers"] = headers
    return request
```

### Pagination Support
```python
def prepare(request, helpers):
    params = request.get("params", {})
    # Arguments are already in params if they have location="query"
    # Set defaults if not provided
    if not params.get("page"):
        params["page"] = 1
    if not params.get("per_page"):
        params["per_page"] = 20
    request["params"] = params
    return request
```

### Response Formatting
```python
def process_response(response, helpers):
    if isinstance(response, dict):
        items = response.get("items", response.get("data", []))
        return {
            "total": len(items),
            "items": items,
            "page": response.get("page", 1)
        }
    return response
```

### State Management Patterns

### Authentication with Persistent Tokens
```python
# In a login command's response_code
def process_response(response, helpers):
    if isinstance(response, dict) and "access_token" in response:
        # Save the token for future requests
        helpers.state_set("auth_token", response["access_token"])
        helpers.state_set("user_id", response.get("user_id"))
        return {"status": "logged in", "user_id": response.get("user_id")}
    return response

# In other commands' prepare_code
def prepare(request, helpers):
    # Use the saved token
    token = helpers.state_get("auth_token")
    if token:
        headers = request.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        request["headers"] = headers
    return request
```

### Session Management
```python
# Save session cookies or session IDs
def process_response(response, helpers):
    if isinstance(response, dict) and "session_id" in response:
        helpers.state_set("session_id", response["session_id"])
        helpers.state_set("session_expires", response.get("expires_at"))
    return response

# Use session in subsequent requests
def prepare(request, helpers):
    session_id = helpers.state_get("session_id")
    if session_id:
        headers = request.get("headers", {})
        headers["X-Session-ID"] = session_id
        request["headers"] = headers
    return request
```

### Current Context Tracking
```python
# Track current working context (project, workspace, etc.)
def process_response(response, helpers):
    if isinstance(response, dict) and "current_project" in response:
        helpers.state_set("current_project", response["current_project"])
        helpers.state_set("project_settings", response.get("settings", {}))
    return response

# Use context in other commands
def prepare(request, helpers):
    current_project = helpers.state_get("current_project")
    if current_project:
        # Add project context to requests automatically
        body = request.get("json", {})
        body["project_id"] = current_project
        request["json"] = body
    return request
```

### Logout/Cleanup
```python
# Clear all state on logout
def process_response(response, helpers):
    if isinstance(response, dict) and response.get("status") == "logged_out":
        helpers.state_clear()  # Remove all stored state
        return {"status": "logged out successfully"}
    return response
```

Now proceed with generating the command configuration based on the user's requirements.
```

## Built-in State Management Commands

The Dynamic CLI provides built-in commands for managing persistent state:

- **`dynamic-cli state show`** - Display all stored state data
- **`dynamic-cli state get <key>`** - Get a specific state value by key
- **`dynamic-cli state set <key> <value>`** - Set a state value (JSON strings for complex objects)
- **`dynamic-cli state delete <key>`** - Delete a specific state key
- **`dynamic-cli state clear`** - Clear all stored state data
- **`dynamic-cli state keys`** - List all state keys

### Examples:
```bash
# Set simple values
dynamic-cli state set auth_token "abc123"
dynamic-cli state set user_id "42"

# Set complex JSON objects
dynamic-cli state set user_data '{"id": 123, "name": "John", "role": "admin"}'

# Get values
dynamic-cli state get auth_token
dynamic-cli state get user_data

# List all keys
dynamic-cli state keys

# Show all state
dynamic-cli state show

# Clean up
dynamic-cli state delete auth_token
dynamic-cli state clear
```

## Usage

To use this prompt:

1. Copy the entire prompt template above
2. Provide the specific API details and requirements after the prompt
3. The LLM will read the existing config, generate the new command, and update the file
4. Verify the generated configuration is correct before using it

## Example Request

"Using the above prompt, generate a command for the GitHub API to list repositories for a user. The API endpoint is `GET https://api.github.com/users/{username}/repos` and requires no authentication. Add options for `--type` (public/private/all) and `--sort` (created/updated/pushed/full_name)."