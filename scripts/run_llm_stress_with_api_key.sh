#!/usr/bin/env bash
# Run LLM agent pipeline stress tests that call real Gemini (A1, A2, A3).
# Requires GEMINI_API_KEY in the environment.
#
# Usage:
#   export GEMINI_API_KEY=your_key_here
#   ./scripts/run_llm_stress_with_api_key.sh
#
# Or one-liner:
#   GEMINI_API_KEY=your_key pytest tests/test_llm_agent_pipeline_stress.py -v -k live

set -e
cd "$(dirname "$0")/.."

if [ -z "${GEMINI_API_KEY}" ]; then
  echo "GEMINI_API_KEY is not set. Export it first, e.g.:"
  echo "  export GEMINI_API_KEY=your_key_here"
  exit 1
fi

.venv/bin/python -m pytest tests/test_llm_agent_pipeline_stress.py -v -k live --tb=short
