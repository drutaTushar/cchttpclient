---
id: storage.list
command: storage
subcommand: list
---
List objects stored in a bucket. The request is enriched with authorization
headers and defaults when the script runs.

```python
def prepare(request, helpers):
    headers = request.get("headers", {})
    headers.setdefault("Authorization", f"Bearer {helpers.secret('supabase_api_key')}")
    headers.setdefault("X-Project-Id", helpers.secret("supabase_project_id"))

    request["headers"] = headers

    # Provide a default prefix if the user omitted it
    params = request.get("params", {})
    if not params.get("prefix"):
        params["prefix"] = helpers.env("DEFAULT_STORAGE_PREFIX", "")
    request["params"] = params
    return request


def process_response(response, helpers):
    objects = response.get("objects", []) if isinstance(response, dict) else []
    return {
        "count": len(objects),
        "objects": objects,
    }
```

---
id: database.query
command: database
subcommand: query
---
Execute a SQL statement against the remote database API. The script injects
credentials and ensures the payload matches the backend requirements.

```python
def prepare(request, helpers):
    headers = request.get("headers", {})
    headers.setdefault("apikey", helpers.secret("supabase_api_key"))
    headers.setdefault("Authorization", f"Bearer {helpers.secret('supabase_api_key')}")
    headers.setdefault("X-Client-Info", "dynamic-cli/1.0")
    request["headers"] = headers

    body = request.get("json", {})
    body.setdefault("project_id", helpers.secret("supabase_project_id"))
    body.setdefault("role", helpers.env("SUPABASE_ROLE", "service_role"))
    request["json"] = body
    return request


def process_response(response, helpers):
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response
```
---
id: test.echo
command: test
subcommand: echo
---
Simple echo command that returns the message back without making external HTTP calls.
This is useful for testing the CLI and MCP server functionality.

```python
def prepare(request, helpers):
    # Skip the HTTP request entirely for this test command
    # Just return a mock response structure
    return None  # Signal to skip HTTP call

def process_response(response, helpers):
    # Since we skipped the HTTP call, create our own response
    # The message should be available in the request context
    return {
        "echo": "Test command executed successfully",
        "timestamp": helpers.env("TEST_TIMESTAMP", "now"),
        "status": "success"
    }
```
---
