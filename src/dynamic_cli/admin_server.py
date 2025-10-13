"""Model Context Protocol server exposing command metadata."""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import openai
import typer
import uvicorn

from .cli import CommandRuntime, _create_handler
from .config import CLIConfig

# Embedded admin HTML template
ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>Dynamic CLI Control Panel</title>
    <style>
        body { 
            font-family: system-ui, sans-serif; 
            margin: 0; 
            background: #f5f5f5; 
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        h1 { margin-top: 0; color: #333; }
        h2 { color: #555; border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }
        section { 
            background: white; 
            padding: 1.5rem; 
            border-radius: 8px; 
            margin-bottom: 1.5rem; 
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); 
        }
        textarea { 
            width: 100%; 
            min-height: 120px; 
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 0.5rem;
            resize: vertical;
        }
        .code-editor {
            min-height: 200px;
        }
        button { 
            padding: 0.75rem 1.5rem; 
            margin-right: 0.5rem; 
            margin-bottom: 0.5rem;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 500;
        }
        .btn-primary { background: #007bff; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-secondary:hover { background: #545b62; }
        .btn-success:hover { background: #1e7e34; }
        .btn-danger:hover { background: #bd2130; }
        
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #ddd; }
        th { background: #f8f9fa; font-weight: 600; }
        tr:hover { background: #f8f9fa; }
        
        label { 
            display: block; 
            font-weight: 600; 
            margin-bottom: 0.25rem; 
            color: #555;
        }
        input[type="text"], input[type="number"], select { 
            width: 100%; 
            padding: 0.5rem; 
            margin-bottom: 1rem; 
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        #test-output { 
            white-space: pre-wrap; 
            background: #1a1a1a; 
            color: #e5e5e5; 
            padding: 1rem; 
            border-radius: 6px; 
            min-height: 100px; 
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        }
        .status {
            padding: 0.5rem;
            margin-left: 1rem;
            border-radius: 4px;
            font-weight: 500;
        }
        .status.success { background: #d4edda; color: #155724; }
        .status.error { background: #f8d7da; color: #721c24; }
        .status.info { background: #cce7ff; color: #004085; }
        
        .tabs {
            display: flex;
            border-bottom: 1px solid #ddd;
            margin-bottom: 1rem;
        }
        .tab {
            padding: 0.75rem 1.5rem;
            cursor: pointer;
            border: none;
            background: none;
            border-bottom: 2px solid transparent;
        }
        .tab.active {
            border-bottom-color: #007bff;
            color: #007bff;
            font-weight: 600;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        
        .command-actions {
            display: flex;
            gap: 0.5rem;
        }
        .command-actions button {
            padding: 0.25rem 0.5rem;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Dynamic CLI Control Panel</h1>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('commands')">Commands</button>
            <button class="tab" onclick="showTab('create')">Create Command</button>
            <button class="tab" onclick="showTab('test')">Test</button>
            <button class="tab" onclick="showTab('validation')">Query Validation</button>
            <button class="tab" onclick="showTab('config')">Raw Config</button>
        </div>

        <!-- Commands Tab -->
        <div id="commands-tab" class="tab-content active">
            <section>
                <h2>Command Catalog</h2>
                <p>Manage your CLI commands. Commands are stored in a single JSON configuration file.</p>
                <table id="command-table">
                    <thead>
                        <tr>
                            <th>Command</th>
                            <th>Subcommand</th>
                            <th>Description</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
                <button class="btn-secondary" onclick="refreshCommands()">Refresh</button>
            </section>
        </div>

        <!-- Create Command Tab -->
        <div id="create-tab" class="tab-content">
            <section>
                <h2>Create New Command</h2>
                <form id="command-form">
                    <div class="form-grid">
                        <div class="form-group">
                            <label for="cmd-name">Command Name</label>
                            <input type="text" id="cmd-name" placeholder="e.g. storage" required>
                        </div>
                        <div class="form-group">
                            <label for="cmd-subcommand">Subcommand</label>
                            <input type="text" id="cmd-subcommand" placeholder="e.g. upload" required>
                        </div>
                        <div class="form-group">
                            <label for="cmd-method">HTTP Method</label>
                            <select id="cmd-method">
                                <option value="GET">GET</option>
                                <option value="POST">POST</option>
                                <option value="PUT">PUT</option>
                                <option value="DELETE">DELETE</option>
                                <option value="PATCH">PATCH</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="cmd-help">Help Text</label>
                        <input type="text" id="cmd-help" placeholder="Brief description of what this command does">
                    </div>
                    
                    <div class="form-group">
                        <label for="cmd-url">URL Template</label>
                        <input type="text" id="cmd-url" placeholder="https://api.example.com/v1/{resource}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="cmd-description">Command Description (for AI)</label>
                        <textarea id="cmd-description" placeholder="Describe what this command should do. This will be used to generate the request/response processing code."></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label for="processor-prompt">Processing Instructions (for AI)</label>
                        <textarea id="processor-prompt" placeholder="Describe how to process the request and response. E.g., 'Add authorization headers, format the response to show only the data field'"></textarea>
                    </div>
                    
                    <div class="form-group">
                        <button type="button" class="btn-primary" onclick="generateCode()">Generate Code with AI</button>
                        <span id="generate-status" class="status"></span>
                    </div>
                    
                    <div class="form-group">
                        <label for="prepare-code">Request Preparation Code</label>
                        <textarea id="prepare-code" class="code-editor" placeholder="def prepare(request, helpers):&#10;    return request"></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label for="response-code">Response Processing Code</label>
                        <textarea id="response-code" class="code-editor" placeholder="def process_response(response, helpers):&#10;    return response"></textarea>
                    </div>
                    
                    <button type="submit" class="btn-success">Create Command</button>
                    <span id="create-status" class="status"></span>
                </form>
            </section>
        </div>

        <!-- Test Tab -->
        <div id="test-tab" class="tab-content">
            <section>
                <h2>Command Test Harness</h2>
                <div class="form-grid">
                    <div class="form-group">
                        <label for="test-command">Command</label>
                        <input type="text" id="test-command" placeholder="e.g. storage" />
                    </div>
                    <div class="form-group">
                        <label for="test-subcommand">Subcommand</label>
                        <input type="text" id="test-subcommand" placeholder="e.g. upload" />
                    </div>
                </div>
                <div class="form-group">
                    <label for="test-arguments">Arguments JSON</label>
                    <textarea id="test-arguments" placeholder='{"bucket": "demo", "payload": "{...}"}'></textarea>
                </div>
                <button class="btn-primary" onclick="runTest()">Run Test</button>
                <span id="test-status" class="status"></span>
                
                <h3>Result</h3>
                <pre id="test-output"></pre>
            </section>
        </div>

        <!-- Query Validation Tab -->
        <div id="validation-tab" class="tab-content">
            <h2>Query Validation</h2>
            <p>Manage validated query mappings for improved accuracy and performance.</p>
            
            <section>
                <h3>Add Validated Query</h3>
                <div class="form-group">
                    <label for="validation-query">Query Text:</label>
                    <input type="text" id="validation-query" placeholder="e.g., get list of users" style="width: 100%; padding: 0.5rem; margin-bottom: 1rem;">
                </div>
                <div class="form-group">
                    <label for="validation-command">Command:</label>
                    <input type="text" id="validation-command" placeholder="e.g., jp" style="width: 100%; padding: 0.5rem; margin-bottom: 1rem;">
                </div>
                <div class="form-group">
                    <label for="validation-subcommand">Subcommand:</label>
                    <input type="text" id="validation-subcommand" placeholder="e.g., users" style="width: 100%; padding: 0.5rem; margin-bottom: 1rem;">
                </div>
                <div class="form-group">
                    <label for="validation-confidence">Confidence (0.0-1.0):</label>
                    <input type="number" id="validation-confidence" min="0" max="1" step="0.1" value="1.0" style="width: 100%; padding: 0.5rem; margin-bottom: 1rem;">
                </div>
                <button class="btn-success" onclick="addValidatedQuery()">Add Validated Query</button>
            </section>

            <section>
                <h3>Existing Validated Queries</h3>
                <table id="validation-table">
                    <thead>
                        <tr>
                            <th>Query Text</th>
                            <th>Command</th>
                            <th>Subcommand</th>
                            <th>Confidence</th>
                            <th>Created At</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Populated by JavaScript -->
                    </tbody>
                </table>
            </section>
        </div>

        <!-- Raw Config Tab -->
        <div id="config-tab" class="tab-content">
            <section>
                <h2>Raw Configuration</h2>
                <p>Direct JSON configuration editing. Changes here will be reflected immediately.</p>
                <textarea id="config-editor" class="code-editor"></textarea>
                <div style="margin-top: 1rem;">
                    <button class="btn-success" onclick="saveConfig()">Save</button>
                    <button class="btn-secondary" onclick="loadConfig()">Reload</button>
                    <span id="config-status" class="status"></span>
                </div>
            </section>
        </div>
    </div>

    <script>
        // Tab management
        function showTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Show selected tab
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }

        // Command management
        async function refreshCommands() {
            try {
                const response = await fetch('/commands');
                const data = await response.json();
                const tbody = document.querySelector('#command-table tbody');
                tbody.innerHTML = '';
                
                data.results.forEach((item) => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${item.command}</td>
                        <td>${item.subcommand}</td>
                        <td>${item.description}</td>
                        <td class="command-actions">
                            <button class="btn-secondary" onclick="editCommand('${item.command}', '${item.subcommand}')">Edit</button>
                            <button class="btn-danger" onclick="deleteCommand('${item.command}', '${item.subcommand}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            } catch (error) {
                console.error('Failed to refresh commands:', error);
            }
        }

        async function editCommand(command, subcommand) {
            // TODO: Implement edit functionality
            alert('Edit functionality will be implemented');
        }

        async function deleteCommand(command, subcommand) {
            if (!confirm(`Delete ${command} ${subcommand}?`)) return;
            
            try {
                const response = await fetch('/commands', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command, subcommand })
                });
                
                if (response.ok) {
                    refreshCommands();
                } else {
                    alert('Failed to delete command');
                }
            } catch (error) {
                console.error('Failed to delete command:', error);
            }
        }

        // AI Code Generation
        async function generateCode() {
            const description = document.getElementById('cmd-description').value;
            const processorPrompt = document.getElementById('processor-prompt').value;
            const method = document.getElementById('cmd-method').value;
            const url = document.getElementById('cmd-url').value;
            
            if (!description || !processorPrompt) {
                document.getElementById('generate-status').textContent = 'Please provide both description and processing instructions';
                document.getElementById('generate-status').className = 'status error';
                return;
            }
            
            document.getElementById('generate-status').textContent = 'Generating code...';
            document.getElementById('generate-status').className = 'status info';
            
            try {
                const response = await fetch('/generate-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        description,
                        processor_prompt: processorPrompt,
                        method,
                        url
                    })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('prepare-code').value = data.prepare_code;
                    document.getElementById('response-code').value = data.response_code;
                    document.getElementById('generate-status').textContent = 'Code generated successfully!';
                    document.getElementById('generate-status').className = 'status success';
                } else {
                    const error = await response.json();
                    document.getElementById('generate-status').textContent = error.detail || 'Failed to generate code';
                    document.getElementById('generate-status').className = 'status error';
                }
            } catch (error) {
                document.getElementById('generate-status').textContent = 'Error: ' + error.message;
                document.getElementById('generate-status').className = 'status error';
            }
        }

        // Command creation
        document.getElementById('command-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = {
                command: document.getElementById('cmd-name').value,
                subcommand: document.getElementById('cmd-subcommand').value,
                help: document.getElementById('cmd-help').value,
                method: document.getElementById('cmd-method').value,
                url: document.getElementById('cmd-url').value,
                prepare_code: document.getElementById('prepare-code').value,
                response_code: document.getElementById('response-code').value
            };
            
            document.getElementById('create-status').textContent = 'Creating command...';
            document.getElementById('create-status').className = 'status info';
            
            try {
                const response = await fetch('/commands', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                
                if (response.ok) {
                    document.getElementById('create-status').textContent = 'Command created successfully!';
                    document.getElementById('create-status').className = 'status success';
                    document.getElementById('command-form').reset();
                    refreshCommands();
                } else {
                    const error = await response.json();
                    document.getElementById('create-status').textContent = error.detail || 'Failed to create command';
                    document.getElementById('create-status').className = 'status error';
                }
            } catch (error) {
                document.getElementById('create-status').textContent = 'Error: ' + error.message;
                document.getElementById('create-status').className = 'status error';
            }
        });

        // Config management
        async function loadConfig() {
            try {
                const response = await fetch('/config');
                const data = await response.json();
                document.getElementById('config-editor').value = data.content;
                document.getElementById('config-status').textContent = 'Loaded';
                document.getElementById('config-status').className = 'status success';
            } catch (error) {
                document.getElementById('config-status').textContent = 'Failed to load';
                document.getElementById('config-status').className = 'status error';
            }
        }

        async function saveConfig() {
            const content = document.getElementById('config-editor').value;
            try {
                const response = await fetch('/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                });
                
                if (response.ok) {
                    document.getElementById('config-status').textContent = 'Saved';
                    document.getElementById('config-status').className = 'status success';
                    refreshCommands();
                } else {
                    const data = await response.json();
                    document.getElementById('config-status').textContent = data.detail || 'Save failed';
                    document.getElementById('config-status').className = 'status error';
                }
            } catch (error) {
                document.getElementById('config-status').textContent = 'Error: ' + error.message;
                document.getElementById('config-status').className = 'status error';
            }
        }

        // Test functionality
        async function runTest() {
            const command = document.getElementById('test-command').value;
            const subcommand = document.getElementById('test-subcommand').value;
            let argsText = document.getElementById('test-arguments').value;
            let args = {};
            
            if (argsText.trim()) {
                try {
                    args = JSON.parse(argsText);
                } catch (err) {
                    document.getElementById('test-status').textContent = 'Invalid JSON';
                    document.getElementById('test-status').className = 'status error';
                    return;
                }
            }
            
            document.getElementById('test-status').textContent = 'Running...';
            document.getElementById('test-status').className = 'status info';
            
            try {
                const response = await fetch('/test-command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command, subcommand, arguments: args })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('test-output').textContent = typeof data.output === 'string' ? data.output : JSON.stringify(data.output, null, 2);
                    document.getElementById('test-status').textContent = 'Success';
                    document.getElementById('test-status').className = 'status success';
                } else {
                    const data = await response.json();
                    document.getElementById('test-status').textContent = data.detail || 'Error running command';
                    document.getElementById('test-status').className = 'status error';
                    document.getElementById('test-output').textContent = '';
                }
            } catch (error) {
                document.getElementById('test-status').textContent = 'Error: ' + error.message;
                document.getElementById('test-status').className = 'status error';
            }
        }

        // Query Validation Management
        async function addValidatedQuery() {
            const queryText = document.getElementById('validation-query').value;
            const command = document.getElementById('validation-command').value;
            const subcommand = document.getElementById('validation-subcommand').value;
            const confidence = parseFloat(document.getElementById('validation-confidence').value);
            
            if (!queryText || !command || !subcommand) {
                alert('Please fill all required fields');
                return;
            }
            
            try {
                const response = await fetch('/validated-queries', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        query_text: queryText,
                        command: command,
                        subcommand: subcommand,
                        confidence: confidence
                    })
                });
                
                if (response.ok) {
                    // Clear form
                    document.getElementById('validation-query').value = '';
                    document.getElementById('validation-command').value = '';
                    document.getElementById('validation-subcommand').value = '';
                    document.getElementById('validation-confidence').value = '1.0';
                    
                    // Refresh table
                    loadValidatedQueries();
                } else {
                    const error = await response.json();
                    alert(error.detail || 'Failed to add validated query');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        async function loadValidatedQueries() {
            try {
                const response = await fetch('/validated-queries');
                const data = await response.json();
                const tbody = document.querySelector('#validation-table tbody');
                tbody.innerHTML = '';
                
                data.results.forEach((item) => {
                    const row = document.createElement('tr');
                    const createdAt = new Date(item.created_at).toLocaleString();
                    row.innerHTML = `
                        <td>${item.query_text}</td>
                        <td>${item.command}</td>
                        <td>${item.subcommand}</td>
                        <td>${item.confidence}</td>
                        <td>${createdAt}</td>
                        <td class="command-actions">
                            <button class="btn-danger" onclick="deleteValidatedQuery(${item.id})">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            } catch (error) {
                console.error('Failed to load validated queries:', error);
            }
        }
        
        async function deleteValidatedQuery(queryId) {
            if (!confirm('Delete this validated query?')) return;
            
            try {
                const response = await fetch(`/validated-queries/${queryId}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    loadValidatedQueries();
                } else {
                    alert('Failed to delete validated query');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            refreshCommands();
            loadConfig();
            loadValidatedQueries();
        });
    </script>
</body>
</html>"""
from .embedding import EmbeddingRecord, EmbeddingStore


class QueryRequest(BaseModel):
    query: str
    top_k: int | None = None


class CommandResponse(BaseModel):
    command: str
    subcommand: str
    section_id: str
    description: str
    score: float
    request_schema: Dict[str, Any] = Field(alias="schema")


class QueryResponse(BaseModel):
    results: List[CommandResponse]


class TestCommandRequest(BaseModel):
    command: str
    subcommand: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class GenerateCodeRequest(BaseModel):
    description: str
    processor_prompt: str
    method: str = "GET"
    url: str = ""


class CreateCommandRequest(BaseModel):
    command: str
    subcommand: str
    help: str = ""
    method: str = "GET"
    url: str
    prepare_code: str = ""
    response_code: str = ""


class DeleteCommandRequest(BaseModel):
    command: str
    subcommand: str


# MCP Protocol Models
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Dict[str, Any] | None = None
    error: Dict[str, Any] | None = None


class MCPTool(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]




class MCPApplication:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._load_config()
        self.store = EmbeddingStore.from_settings(self.config.mcp)
        self._build_index()
        self.app = FastAPI(title="Dynamic CLI MCP Server")
        self._register_routes()

    def _load_config(self) -> None:
        self.config = CLIConfig.load(self.config_path)

    def _reload_config(self) -> None:
        previous_store = getattr(self, "store", None)
        self._load_config()
        previous_path = getattr(previous_store, "path", None)
        if previous_path is None or previous_path != self.config.mcp.persist_path:
            self.store = EmbeddingStore.from_settings(self.config.mcp)
        self._build_index()

    def _build_index(self):
        records: List[EmbeddingRecord] = []
        for command in self.config.commands:
            for subcommand in command.subcommands:
                section_id = f"{command.name}.{subcommand.name}"
                
                # Create description from help text and code comments
                description = subcommand.help
                if subcommand.prepare_code:
                    # Extract comments from code as additional context
                    code_lines = subcommand.prepare_code.split('\n')
                    comments = [line.strip()[1:].strip() for line in code_lines if line.strip().startswith('#')]
                    if comments:
                        description += " " + " ".join(comments)
                
                schema = _serialize_schema(command.name, subcommand, description)
                records.append(
                    EmbeddingRecord(
                        section_id=section_id,
                        command=command.name,
                        subcommand=subcommand.name,
                        description=description,
                        schema=schema,
                    )
                )
        self.store.rebuild(records)

    def _register_routes(self):
        app = self.app

        @app.get("/commands")
        def list_commands() -> QueryResponse:
            records = self.store.all()
            results = [
                CommandResponse(
                    command=record.command,
                    subcommand=record.subcommand,
                    section_id=record.section_id,
                    description=record.description,
                    score=0.0,
                    schema=record.schema,
                )
                for record in records
            ]
            return QueryResponse(results=results)

        @app.post("/query")
        def query_endpoint(request: QueryRequest) -> QueryResponse:
            if not request.query.strip():
                raise HTTPException(status_code=400, detail="Query must not be empty")
            matches = self.store.query(request.query, top_k=request.top_k or self.config.mcp.top_k)
            results = [
                CommandResponse(
                    command=record.command,
                    subcommand=record.subcommand,
                    section_id=record.section_id,
                    description=record.description,
                    score=score,
                    schema=record.schema,
                )
                for record, score in matches
            ]
            return QueryResponse(results=results)

        @app.get("/config")
        def read_config() -> Dict[str, Any]:
            return {"content": self.config_path.read_text(encoding="utf-8")}

        class ConfigUpdateRequest(BaseModel):
            content: str

        @app.put("/config")
        def update_config(payload: ConfigUpdateRequest) -> Dict[str, Any]:
            try:
                parsed = json.loads(payload.content)
            except json.JSONDecodeError as exc:  # pragma: no cover - validated in UI usage
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

            self.config_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            self._reload_config()
            return {"status": "ok"}

        @app.post("/test-command")
        def test_command(payload: TestCommandRequest = Body(...)) -> Dict[str, Any]:
            import logging
            logging.basicConfig(level=logging.INFO)
            logger = logging.getLogger(__name__)
            
            logger.info(f"Test command request: command={payload.command}, subcommand={payload.subcommand}, args={payload.arguments}")
            
            runtime = CommandRuntime(self.config)
            command = next((cmd for cmd in self.config.commands if cmd.name == payload.command), None)
            if not command:
                logger.error(f"Command '{payload.command}' not found. Available commands: {[cmd.name for cmd in self.config.commands]}")
                raise HTTPException(status_code=404, detail="Command not found")
            subcommand = next((sub for sub in command.subcommands if sub.name == payload.subcommand), None)
            if not subcommand:
                logger.error(f"Subcommand '{payload.subcommand}' not found in command '{payload.command}'. Available subcommands: {[sub.name for sub in command.subcommands]}")
                raise HTTPException(status_code=404, detail="Subcommand not found")

            logger.info(f"Found subcommand definition: {payload.command}.{payload.subcommand}")
            
            handler = _create_handler(runtime, subcommand)
            buffer = io.StringIO()
            try:
                logger.info(f"Executing handler with arguments: {payload.arguments}")
                with contextlib.redirect_stdout(buffer):
                    handler(**payload.arguments)
                logger.info("Handler executed successfully")
            except Exception as exc:  # pragma: no cover - runtime errors surfaced to client
                logger.error(f"Handler execution failed: {exc}")
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            output = buffer.getvalue().strip()
            logger.info(f"Handler output: {output}")
            try:
                parsed_output = json.loads(output)
            except json.JSONDecodeError:
                parsed_output = output
            return {"output": parsed_output}

        @app.post("/generate-code")
        def generate_code(request: GenerateCodeRequest) -> Dict[str, str]:
            """Generate prepare and response code using OpenAI."""
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise HTTPException(status_code=400, detail="OpenAI API key not configured")
                
                client = openai.OpenAI(api_key=api_key)
                
                prompt = f"""
                Generate EXACTLY two Python functions for a CLI command. Do not include any other code, explanations, imports, main functions, or example usage.

                Requirements:
                - Command Description: {request.description}
                - Processing Instructions: {request.processor_prompt}
                - HTTP Method: {request.method}
                - URL Template: {request.url}

                STRICT FORMAT REQUIREMENTS:
                1. Generate ONLY these two functions, nothing else
                2. No imports, no main function, no example code
                3. No markdown code blocks or backticks
                4. No explanatory text before or after the functions

                Function 1: prepare(request, helpers)
                - Takes a request dict with: method, url, headers, params, json, data
                - Returns the modified request dict
                - Available helpers: 
                  * helpers.secret(name): Get configured secrets
                  * helpers.env(key, default): Get environment variables
                  * helpers.json(value): Parse/serialize JSON data
                  * helpers.dumps(value): Serialize to JSON string
                  * helpers.loads(value): Parse JSON string

                Function 2: process_response(response, helpers)
                - Takes the HTTP response (already parsed dict/list for JSON responses, string for text)
                - Returns processed data for CLI output (dict, list, or string)
                - Available helpers: 
                  * helpers.secret(name): Get configured secrets
                  * helpers.env(key, default): Get environment variables  
                  * helpers.json(value): Parse/serialize JSON data
                  * helpers.get(dict, key, default): Safe dict access
                  * helpers.filter(items, key, value): Filter list of dicts
                  * helpers.map(items, keys): Extract specific keys from dicts

                Example format (adapt to requirements):
                def prepare(request, helpers):
                    return request

                def process_response(response, helpers):
                    return response

                Generate functions that match the description and processing requirements above.
                """

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a Python code generator. You MUST output ONLY the two requested functions with NO additional code, imports, explanations, or markdown. Follow the format exactly."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=800
                )

                generated_code = response.choices[0].message.content.strip()
                
                # Clean up any markdown artifacts
                generated_code = generated_code.replace('```python', '').replace('```', '').strip()
                
                # Split the code into prepare and response functions
                code_lines = generated_code.split('\n')
                prepare_lines = []
                response_lines = []
                current_function = None
                indent_level = 0
                
                for line in code_lines:
                    stripped = line.strip()
                    
                    # Skip empty lines outside functions
                    if not stripped and current_function is None:
                        continue
                    
                    # Skip main function and imports
                    if (stripped.startswith('def main(') or 
                        stripped.startswith('if __name__') or
                        stripped.startswith('import ') or
                        stripped.startswith('from ')):
                        current_function = 'skip'
                        continue
                    
                    # Detect function starts
                    if stripped.startswith('def prepare('):
                        current_function = 'prepare'
                        prepare_lines.append(line)
                        indent_level = len(line) - len(line.lstrip())
                    elif stripped.startswith('def process_response('):
                        current_function = 'response'
                        response_lines.append(line)
                        indent_level = len(line) - len(line.lstrip())
                    elif current_function == 'prepare':
                        # Continue with prepare function
                        if stripped and (len(line) - len(line.lstrip())) <= indent_level and not line.startswith(' ') and not line.startswith('\t'):
                            # Function ended, check if it's another function
                            if not stripped.startswith('def '):
                                current_function = None
                        if current_function == 'prepare':
                            prepare_lines.append(line)
                    elif current_function == 'response':
                        # Continue with response function  
                        if stripped and (len(line) - len(line.lstrip())) <= indent_level and not line.startswith(' ') and not line.startswith('\t'):
                            # Function ended, check if it's another function
                            if not stripped.startswith('def '):
                                current_function = None
                        if current_function == 'response':
                            response_lines.append(line)
                    elif current_function == 'skip':
                        # Skip until we find a proper function or reach base indentation
                        if stripped and not line.startswith(' ') and not line.startswith('\t'):
                            current_function = None
                
                prepare_code = '\n'.join(prepare_lines) if prepare_lines else "def prepare(request, helpers):\n    return request"
                response_code = '\n'.join(response_lines) if response_lines else "def process_response(response, helpers):\n    return response"
                
                return {
                    "prepare_code": prepare_code,
                    "response_code": response_code
                }
                
            except Exception as e:
                logging.error(f"Code generation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Code generation failed: {str(e)}")

        @app.post("/commands")
        def create_command(request: CreateCommandRequest) -> Dict[str, str]:
            """Create a new command in the configuration."""
            try:
                # Load current config
                config_data = json.loads(self.config_path.read_text())
                
                # Find or create command group
                command_group = None
                for cmd in config_data.get("commands", []):
                    if cmd["name"] == request.command:
                        command_group = cmd
                        break
                
                if not command_group:
                    command_group = {
                        "name": request.command,
                        "help": f"{request.command} commands",
                        "subcommands": []
                    }
                    config_data.setdefault("commands", []).append(command_group)
                
                # Check if subcommand already exists
                for subcmd in command_group["subcommands"]:
                    if subcmd["name"] == request.subcommand:
                        raise HTTPException(status_code=400, detail="Subcommand already exists")
                
                # Create new subcommand
                new_subcommand = {
                    "name": request.subcommand,
                    "help": request.help,
                    "prepare_code": request.prepare_code or "def prepare(request, helpers):\n    return request",
                    "response_code": request.response_code or "def process_response(response, helpers):\n    return response",
                    "arguments": [],
                    "request": {
                        "method": request.method,
                        "url": request.url,
                        "headers": {"Content-Type": "application/json"} if request.method in ["POST", "PUT", "PATCH"] else {},
                        "query": {},
                        "body": {"mode": "json", "template": {}},
                        "response": {"mode": "json", "success_codes": [200]}
                    }
                }
                
                command_group["subcommands"].append(new_subcommand)
                
                # Save config
                self.config_path.write_text(json.dumps(config_data, indent=2))
                self._reload_config()
                
                return {"status": "created"}
                
            except Exception as e:
                logging.error(f"Command creation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Command creation failed: {str(e)}")

        @app.delete("/commands")
        def delete_command(request: DeleteCommandRequest) -> Dict[str, str]:
            """Delete a command from the configuration."""
            try:
                # Load current config
                config_data = json.loads(self.config_path.read_text())
                
                # Find and remove subcommand
                for cmd in config_data.get("commands", []):
                    if cmd["name"] == request.command:
                        cmd["subcommands"] = [
                            sub for sub in cmd["subcommands"] 
                            if sub["name"] != request.subcommand
                        ]
                        break
                
                # Save config
                self.config_path.write_text(json.dumps(config_data, indent=2))
                self._reload_config()
                
                return {"status": "deleted"}
                
            except Exception as e:
                logging.error(f"Command deletion failed: {e}")
                raise HTTPException(status_code=500, detail=f"Command deletion failed: {str(e)}")

        # Validated Queries API endpoints
        @app.get("/validated-queries")
        def get_validated_queries():
            """Get all validated queries."""
            try:
                if not self.store:
                    return {"results": []}
                
                queries = self.store.get_all_validated_queries()
                return {"results": queries}
            except Exception as e:
                logging.error(f"Failed to get validated queries: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get validated queries: {str(e)}")

        @app.post("/validated-queries")
        def add_validated_query(request: Dict[str, Any]):
            """Add a new validated query mapping."""
            try:
                if not self.store:
                    raise HTTPException(status_code=500, detail="Embedding store not initialized")
                
                query_text = request.get("query_text")
                command = request.get("command")
                subcommand = request.get("subcommand")
                confidence = request.get("confidence", 1.0)
                
                if not query_text or not command or not subcommand:
                    raise HTTPException(status_code=400, detail="Missing required fields: query_text, command, subcommand")
                
                success = self.store.add_validated_query(query_text, command, subcommand, confidence)
                if success:
                    return {"status": "added", "query_text": query_text, "command": command, "subcommand": subcommand}
                else:
                    raise HTTPException(status_code=500, detail="Failed to add validated query")
                    
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Failed to add validated query: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to add validated query: {str(e)}")

        @app.delete("/validated-queries/{query_id}")
        def delete_validated_query(query_id: int):
            """Delete a validated query by ID."""
            try:
                if not self.store:
                    raise HTTPException(status_code=500, detail="Embedding store not initialized")
                
                success = self.store.remove_validated_query(query_id)
                if success:
                    return {"status": "deleted", "query_id": query_id}
                else:
                    raise HTTPException(status_code=404, detail="Validated query not found")
                    
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Failed to delete validated query: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to delete validated query: {str(e)}")

        @app.get("/ui", response_class=HTMLResponse)
        def ui_page() -> HTMLResponse:
            return HTMLResponse(ADMIN_HTML)


def _serialize_schema(command_name: str, subcommand, description: str) -> Dict[str, Any]:
    return {
        "command": command_name,
        "subcommand": subcommand.name,
        "description": description or subcommand.help,
        "arguments": [
            {
                "name": arg.name,
                "help": arg.help,
                "type": arg.type,
                "required": arg.required,
                "location": arg.location,
                "target": arg.target,
            }
            for arg in subcommand.arguments
        ],
        "request": {
            "method": subcommand.request.method,
            "url": subcommand.request.url,
            "headers": subcommand.request.headers,
            "query": subcommand.request.query,
            "body": {
                "mode": subcommand.request.body.mode,
                "template": subcommand.request.body.template,
            },
            "response": {
                "mode": subcommand.request.response.mode,
                "success_codes": subcommand.request.response.success_codes,
            },
        },
    }

def create_app(config_path: Path) -> FastAPI:
    return MCPApplication(config_path).app


cli = typer.Typer(help="Dynamic CLI Admin Server - Web interface for command management")


def find_config_file() -> Optional[Path]:
    """Find the config file in various standard locations."""
    import os
    
    # List of possible config locations (in order of preference)
    possible_paths = [
        # Project-specific config (highest priority)
        Path.cwd() / ".dynamic-cli" / "config.json",
        Path.cwd() / ".dynamic-cli" / "cli_config.json",
        
        # Current working directory
        Path.cwd() / "cli_config.json",
        Path.cwd() / "config" / "cli_config.json",
        
        # Environment variable
        Path(os.getenv("DYNAMIC_CLI_CONFIG", "")) if os.getenv("DYNAMIC_CLI_CONFIG") else None,
        
        # User home directory (fallback)
        Path.home() / ".config" / "dynamic-cli" / "config.json",
        Path.home() / ".dynamic-cli" / "config.json",
        
        # System-wide config (last resort)
        Path("/etc/dynamic-cli/config.json"),
    ]
    
    for config_path in possible_paths:
        if config_path and config_path.exists():
            return config_path
    
    return None


@cli.command()
def serve(
    config: Optional[Path] = typer.Option(None, "--config", help="Path to CLI configuration (auto-detected if not specified)"),
    host: str = typer.Option("127.0.0.1", help="Host to bind"),
    port: int = typer.Option(8765, help="Port to bind"),
):
    """Run the admin server with web interface for command management."""

    # Auto-detect config if not provided
    if not config:
        config = find_config_file()
        if not config:
            typer.echo(
                "❌ No config file found. Please either:\\n"
                "  • Create .dynamic-cli/config.json in current directory (project-specific)\\n"
                "  • Create cli_config.json in current directory\\n"
                "  • Use --config option to specify path explicitly",
                err=True
            )
            raise typer.Exit(1)
        typer.echo(f"📁 Using config: {config}")

    app = create_app(config)
    typer.echo(f"🌐 Admin interface available at: http://{host}:{port}/ui")
    uvicorn.run(app, host=str(host), port=int(port))


if __name__ == "__main__":
    cli()

