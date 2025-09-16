#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
uvicorn mcp_server:app --host 0.0.0.0 --port ${PORT:-5000} --reload
