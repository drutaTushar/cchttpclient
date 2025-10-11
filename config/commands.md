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
