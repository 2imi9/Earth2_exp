# Earth-2 MCP Server & Utilities

This repository packages two complementary components for working with NVIDIA Earth-2 FourCastNet forecasts:

1. A production-oriented **Model Context Protocol (MCP) server** that exposes Earth-2 capabilities to assistants such as ChatGPT Tools and Claude MCP.
2. A set of **standalone FourCastNet utilities** (kept in `fourcastnet-nim/`) for manual experimentation or scripted batch jobs.

The MCP server implements JSON-RPC 2.0 endpoints over both HTTP and WebSocket, forwards tool invocations to an Earth-2 sidecar via asynchronous HTTP calls, and advertises key resources to connected assistants.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # populate secrets before running
uvicorn mcp_server:app --host 0.0.0.0 --port 5000 --reload
```

To streamline setup you can also use the helper scripts:

```bash
./scripts/install.sh
./scripts/run_dev.sh
```

## Configuration

All runtime options are loaded from environment variables. Copy `.env.example` to `.env` and update the values:

```dotenv
MCP_SERVER_NAME=earth2-mcp
MCP_SERVER_VERSION=1.0.0
TARGET_AI_ASSISTANT=ChatGPT
DEPLOYMENT_TYPE=single-node
USE_CASE=forecasting
SECURITY_LEVEL=prod

EARTH2_BASE_URL=http://earth_2_fourcastnet:8000
EARTH2_HEALTH_PATH=/health
EARTH2_FORECAST_PATH=/api/forecast
EARTH2_STREAM_PATH=/api/forecast/stream

NGC_API_KEY=
INTERNAL_API_TOKEN=
PORT=5000
LOG_LEVEL=INFO
```

In production, inject secrets (`NGC_API_KEY`, `INTERNAL_API_TOKEN`) through your orchestrator rather than storing them on disk.

## Running with Docker Compose

Build and launch both the MCP server and the Earth-2 FourCastNet runtime (requires an NVIDIA GPU for the latter):

```bash
docker compose up -d --build
```

The compose file provisions two services:

- `mcp_server` – FastAPI application exposing `/rpc` (HTTP JSON-RPC) and `/ws` (WebSocket JSON-RPC) endpoints.
- `earth_2_fourcastnet` – The downstream Earth-2 container image. Replace `your_nvidia_fourcastnet_image:latest` with the actual image you deploy.

The services share an isolated bridge network and the MCP server does not run as root, enforcing `no-new-privileges` for additional hardening.

## JSON-RPC examples

```bash
# Initialize (advertises capabilities)
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"mcp/initialize","params":{}
}' | jq

# List registered tools
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list","params":{}
}' | jq

# Trigger a forecast
tool_payload='{"location":"40.71,-74.00","start_time":"2025-09-16T00:00:00Z","hours":24}'
curl -s localhost:5000/rpc -H 'Content-Type: application/json' -d "{
  \"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{
    \"name\":\"generate_weather_forecast\",\"arguments\":$tool_payload
  }
}" | jq
```

WebSocket clients (Claude MCP or custom agents) can connect to `ws://<host>:5000/ws` and issue the same JSON-RPC methods.

## Security checklist

- Inject secrets via orchestrator secret stores.
- Keep the MCP server on a private network alongside Earth-2, exposing only the necessary ingress.
- Terminate TLS in a reverse proxy such as nginx, Caddy, or a managed load balancer.
- Retain the non-root container user and consider adding a read-only root filesystem in production deployments.
- Add rate limiting at the proxy level for public-facing deployments.

## FourCastNet utility scripts

The original utilities remain available under `fourcastnet-nim/`. They provide manual tooling for extracting point statistics or submitting raw requests to a FourCastNet NIM endpoint.

### Build the utility container

```bash
docker build -t fourcastnet-client fourcastnet-nim
```

### Run point statistics via Docker Compose

1. Create `fourcastnet-nim/.env` with your NIM API key: `echo "NIM_API_KEY=your_key_here" > fourcastnet-nim/.env`
2. `docker compose -f fourcastnet-nim/docker-compose.yml up --build -d`
3. `docker compose -f fourcastnet-nim/docker-compose.yml exec fourcastnet python point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv`

### Manual container usage

```bash
docker run --rm fourcastnet-client python point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv
```

## Development

Linting and type checking are not enforced automatically, but you can run a quick syntax check before committing:

```bash
python -m py_compile mcp_server.py earth2_bridge.py fourcastnet-nim/make_input.py \
    fourcastnet-nim/point_stats.py fourcastnet-nim/query_nim.py
```
