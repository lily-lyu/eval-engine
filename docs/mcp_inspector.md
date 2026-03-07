# Testing with MCP Inspector

Test the eval-engine MCP server with the **MCP Inspector** before relying on Cursor agent behavior. The Inspector is the standard way to verify tools, resources, prompts, and error shapes.

## Left panel configuration

Configure the Inspector’s **left panel** (server connection) as follows so the server starts correctly and finds the repo. Replace `/Users/Admin/Desktop/VR/eval-engine` with your project root path if different.

| Field | Value |
|-------|--------|
| **Transport Type** | STDIO |
| **Command** | `/Users/Admin/Desktop/VR/eval-engine/.venv/bin/python` |
| **Arguments** | `-m` and `eval_engine.mcp.server` (two arguments) |
| **Environment Variables** | See below |

**Environment Variables** — add these (replace the path with your project root):

- `PYTHONPATH` = `/Users/Admin/Desktop/VR/eval-engine`
- `EVAL_ENGINE_ROOT` = `/Users/Admin/Desktop/VR/eval-engine`

- **PYTHONPATH** – Required so the spawned Python process can import `eval_engine` when the Inspector’s working directory is not the project root.
- **EVAL_ENGINE_ROOT** – Repo root; the server uses it (or `EVAL_ENGINE_PROJECT_ROOT`) to resolve `runs/` and the index. The code accepts either variable.

## Run the Inspector

From the project root:

```bash
./scripts/inspect-mcp.sh
```

The script passes the same Command, Arguments, and env (PYTHONPATH, EVAL_ENGINE_ROOT, EVAL_ENGINE_PROJECT_ROOT) to the Inspector. To match that manually in the left panel, use the table above.

- **Requirements:** Node.js ^22.7.5, `npx`
- **UI:** Open http://localhost:6274 in your browser
- The Inspector spawns the eval-engine server over **stdio** and connects via its proxy (port 6277)

## What to Verify

### 1. Tool discovery

- In the **Tools** tab, confirm all tools are listed:
  - `run_batch`
  - `get_run_summary_tool`
  - `get_item_result`
  - `get_artifact_content`
  - `get_job_status`
  - `run_regression`

### 2. Arg schemas

- For each tool, open it and check that parameters and types match:
  - `run_batch`: `spec_json` (object), `quota` (int), `sut`, `sut_url`, `sut_timeout`, `model_version`
  - `get_run_summary_tool`: `run_id` (string)
  - `get_item_result`: `run_id`, `item_id` (strings)
  - `get_artifact_content`: `run_id`, `filename` (strings)
  - `get_job_status`: `job_id` (string)
  - `run_regression`: `suite_path`, `sut_url` (strings), `sut_timeout`, `min_pass_rate`, `artifacts_dir`

### 3. Resource URIs

- In the **Resources** tab, confirm the resource template:
  - **URI:** `eval://runs/{run_id}/summary`
- Use “Load” or “Subscribe” with a real `run_id` (e.g. from `runs/`) and confirm the run summary JSON is returned.

### 4. Prompt rendering

- If you add `@mcp.prompt()` templates later, use the **Prompts** tab to:
  - See listed prompts and their arguments
  - Run them with sample arguments and check the rendered messages

### 5. Error shapes

- In the **Tools** tab, trigger errors and confirm the response shape:
  - **Unknown run_id:** call `get_run_summary_tool` or `get_item_result` with a non-existent `run_id` → expect `{"error": {"kind": "not_found", "code": "RUN_NOT_FOUND", "message": "...", "details": {...}}}`
  - **Invalid args:** call a tool with wrong types (e.g. `run_id: 123`) → expect `{"error": {"kind": "schema_error", "code": "INVALID_ARGS", ...}}`
  - **Missing artifact:** `get_artifact_content` with valid run but missing filename → expect `{"error": {"kind": "not_found", "code": "ARTIFACT_NOT_FOUND", ...}}`
- Use the **Notifications** pane to see server logs if something fails unexpectedly.

## After Inspector

Once tool discovery, schemas, resources, and error shapes look correct in the Inspector, use the same server config (e.g. `.cursor/mcp.json`) in Cursor and rely on agent behavior with confidence.
