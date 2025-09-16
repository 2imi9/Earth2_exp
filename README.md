# Earth-2 MCP Server & FourCastNet Utilities

Production-ready MCP server that bridges AI assistants to NVIDIA Earth-2 FourCastNet, plus the existing FourCastNet client utilities.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your Earth-2 + security values

# Run locally (dev)
uvicorn mcp_server:app --host 0.0.0.0 --port 5000 --reload

# Or run with Docker Compose (GPU required for the Earth-2 service)
docker compose up -d --build
```

## Configuration

Create `.env` from the example and fill in the values:

```dotenv
# === Core ===
MCP_SERVER_NAME=earth2-mcp
MCP_SERVER_VERSION=1.0.0
TARGET_AI_ASSISTANT=${TARGET_AI_ASSISTANT:-ChatGPT}
DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE:-single-node}
USE_CASE=${USE_CASE:-forecasting}
SECURITY_LEVEL=${SECURITY_LEVEL:-prod}

# === Earth-2 container/API ===
EARTH2_BASE_URL=http://earth_2_fourcastnet:8000
EARTH2_HEALTH_PATH=/health
EARTH2_FORECAST_PATH=/api/forecast
EARTH2_STREAM_PATH=/api/forecast/stream

# === Security / Secrets ===
NGC_API_KEY=replace-me
# Optional: mTLS / API token used between MCP and Earth-2 sidecar
INTERNAL_API_TOKEN=change-me

# === Server ===
PORT=5000
LOG_LEVEL=INFO
```

> In production, inject secrets via Docker/Orchestrator secrets, not plain env files.

## Server overview

The MCP server (see `mcp_server.py`) exposes both HTTP (`/rpc`) and WebSocket (`/ws`) JSON-RPC 2.0 endpoints. It advertises MCP tools that proxy to Earth-2 via the asynchronous client in `earth2_bridge.py`.

Available tools:

- `generate_weather_forecast` – create a FourCastNet forecast for a location/time range.
- `get_forecast_visualization` – fetch pre-rendered PNG output by request ID.
- `analyze_weather_patterns` – run anomaly/trend detection against ERA5/Earth-2 outputs.
- `stream_forecast_data` – request streaming forecast data (cursor placeholder).

Resources advertised to assistants include service health and capability summaries. The dispatcher also implements `mcp/initialize`, `tools/list`, `tools/call`, `resources/list`, and `resources/read` to align with ChatGPT Tools and Claude MCP conventions.

## Earth-2 communication bridge

`earth2_bridge.py` handles REST calls to the downstream Earth-2 container using `aiohttp`, including authentication, health checks, forecast generation, visual retrieval, and streaming cursors. Errors propagate as `JsonRpcError` instances with informative metadata.

## Docker & orchestration

- `Dockerfile` builds the MCP server image using Python 3.11, installs dependencies, and runs Uvicorn as a non-root user.
- `docker-compose.yml` launches the MCP server alongside an Earth-2 FourCastNet container (GPU runtime expected). Health checks gate startup and shared environment variables pass the internal token.
- Optional helper `docker_manager.py` provides basic start/stop/inspect operations using the Docker SDK.

## Scripts

- `scripts/install.sh` – create a virtual environment, install dependencies, and scaffold `.env`.
- `scripts/run_dev.sh` – activate the virtual environment and run the dev server with hot reload.

## JSON-RPC examples

```bash
# Initialize
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"mcp/initialize","params":{}
}' | jq

# List tools
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list","params":{}
}' | jq

# Call forecast
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call","params":{
    "name":"generate_weather_forecast",
    "arguments": {"location":"40.71,-74.00","start_time":"2025-09-16T00:00:00Z","hours":24}
  }
}' | jq
```

## Security checklist

- Inject `NGC_API_KEY` / `INTERNAL_API_TOKEN` via orchestrator secrets.
- Run the MCP server and FourCastNet services on a private bridge network; only expose port 5000 as needed.
- Terminate TLS at a reverse proxy (nginx, Caddy, cloud LB) in front of the MCP server.
- Keep the container non-root, enable `no-new-privileges`, and optionally use a read-only filesystem.
- Redact secrets in logs and centralize logging if running in production.
- Enforce input validation via tool schemas and server-side checks in Earth-2 APIs.
- Apply rate limiting at the proxy layer when exposed publicly.

## Existing FourCastNet utilities

Legacy scripts remain under `fourcastnet-nim/` for direct FourCastNet interactions (e.g., `point_stats.py`, `query_nim.py`) and can still be built/run via the provided Dockerfile. Refer to the existing script documentation for usage.
