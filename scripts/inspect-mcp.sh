#!/usr/bin/env bash
# Run MCP Inspector with the eval-engine server (stdio). Use this to verify
# tool discovery, arg schemas, resource URIs, prompt rendering, and error shapes
# before testing in Cursor.
#
# Requires: Node.js ^22.7.5, npx
# Opens: http://localhost:6274 (Inspector UI)
#
# If you configure the Inspector left panel manually, use the same values
# as in docs/mcp_inspector.md (Transport STDIO, Command, Arguments, PYTHONPATH, EVAL_ENGINE_ROOT).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing .venv. Create one with: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Project root: $PROJECT_ROOT"
echo "Starting MCP Inspector (UI at http://localhost:6274)..."
echo "Server command: $VENV_PYTHON -m eval_engine.mcp.server"
echo "Env: PYTHONPATH=$PROJECT_ROOT EVAL_ENGINE_ROOT=$PROJECT_ROOT"
echo ""

# PYTHONPATH so the spawned process finds eval_engine when cwd is not project root.
# EVAL_ENGINE_ROOT (and EVAL_ENGINE_PROJECT_ROOT) so the server resolves runs/ and index.
npx -y @modelcontextprotocol/inspector \
  -e "PYTHONPATH=$PROJECT_ROOT" \
  -e "EVAL_ENGINE_ROOT=$PROJECT_ROOT" \
  -e "EVAL_ENGINE_PROJECT_ROOT=$PROJECT_ROOT" \
  -- \
  "$VENV_PYTHON" -m eval_engine.mcp.server
