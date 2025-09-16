"""FastAPI-based MCP server bridging to Earth-2 services."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from earth2_bridge import Earth2Client


logger = logging.getLogger("mcp")
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO))

app = FastAPI(title=settings.MCP_SERVER_NAME, version=settings.MCP_SERVER_VERSION)


# -----------------------------
# JSON-RPC core
# -----------------------------


class JsonRpcError(Exception):
    """Exception carrying JSON-RPC error metadata."""

    def __init__(self, code: int, message: str, data: Optional[dict] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data or {}


class JsonRpc:
    """Utility helpers for working with JSON-RPC envelopes."""

    @staticmethod
    def response(id_: Any, result: Any | None = None, error: JsonRpcError | None = None) -> Dict[str, Any]:
        if error:
            body: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": error.code, "message": str(error), "data": error.data},
            }
        else:
            body = {"jsonrpc": "2.0", "id": id_, "result": result}
        return body

    @staticmethod
    def parse(payload: Dict[str, Any]) -> tuple[str, Dict[str, Any], Any]:
        if payload.get("jsonrpc") != "2.0":
            raise JsonRpcError(-32600, "Invalid Request: jsonrpc must be '2.0'")
        method = payload.get("method")
        if not method:
            raise JsonRpcError(-32600, "Invalid Request: missing method")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "Invalid params: expected object")
        return method, params, payload.get("id")


# -----------------------------
# MCP registries & types
# -----------------------------


ToolFunc = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]] | Dict[str, Any]]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any] = {}


class Resource(BaseModel):
    uri: str
    mime_type: str
    description: Optional[str] = None


class ToolRegistry:
    """Registry mapping tool specs to handlers."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolFunc] = {}

    def register(self, spec: ToolSpec, handler: ToolFunc) -> None:
        self._tools[spec.name] = spec
        self._handlers[spec.name] = handler
        logger.info("Registered tool %s", spec.name)

    def list_specs(self) -> List[Dict[str, Any]]:
        return [tool.model_dump() for tool in self._tools.values()]

    async def call(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._handlers:
            raise JsonRpcError(-32601, f"Tool not found: {name}")
        handler = self._handlers[name]
        if asyncio.iscoroutinefunction(handler):
            result = await handler(params)  # type: ignore[arg-type]
        else:
            maybe_result = handler(params)
            if asyncio.iscoroutine(maybe_result):
                result = await maybe_result
            else:
                result = maybe_result
        if not isinstance(result, dict):
            raise JsonRpcError(-32603, "Tool handler must return a dict")
        return result


class ResourceRegistry:
    """In-memory registry for simple informational resources."""

    def __init__(self) -> None:
        self._resources: Dict[str, Resource] = {}

    def add(self, res: Resource) -> None:
        self._resources[res.uri] = res

    def list(self) -> List[Dict[str, Any]]:
        return [resource.model_dump() for resource in self._resources.values()]

    def read(self, uri: str) -> Dict[str, Any]:
        if uri not in self._resources:
            raise JsonRpcError(-32602, f"Unknown resource: {uri}")
        resource = self._resources[uri]
        return {
            "uri": uri,
            "mime_type": resource.mime_type,
            "content": f"Resource body for {uri} generated at {time.time()}",
            "description": resource.description,
        }


# -----------------------------
# Handlers implementing MCP methods
# -----------------------------


tools = ToolRegistry()
resources = ResourceRegistry()
earth2 = Earth2Client()

# Example resources (advertise capabilities/configs to assistants)
resources.add(
    Resource(
        uri="resource://earth2/health",
        mime_type="application/json",
        description="Earth-2 service health",
    )
)
resources.add(
    Resource(
        uri="resource://earth2/capabilities",
        mime_type="application/json",
        description="Advertised model capabilities",
    )
)


def _register_forecast_tool() -> None:
    spec = ToolSpec(
        name="generate_weather_forecast",
        description="Generate a short-range forecast via Earth-2 FourCastNet",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "lat,lon or place name"},
                "start_time": {"type": "string", "description": "ISO8601"},
                "hours": {"type": "integer", "minimum": 1, "maximum": 240},
            },
            "required": ["location", "start_time", "hours"],
        },
    )

    async def handler(params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await earth2.generate_forecast(params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("forecast failure")
            raise JsonRpcError(500, "Forecast failed", {"detail": str(exc)})

    tools.register(spec, handler)


def _register_visual_tool() -> None:
    spec = ToolSpec(
        name="get_forecast_visualization",
        description="Render forecast visualization (PNG) for a request id",
        input_schema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    )

    async def handler(params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await earth2.get_visual(params["request_id"])
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("visualization failure")
            raise JsonRpcError(500, "Visualization failed", {"detail": str(exc)})

    tools.register(spec, handler)


def _register_patterns_tool() -> None:
    spec = ToolSpec(
        name="analyze_weather_patterns",
        description="Analyze ERA5/Earth-2 outputs for trends/anomalies",
        input_schema={
            "type": "object",
            "properties": {"bbox": {"type": "array"}},
            "required": ["bbox"],
        },
    )

    async def handler(params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await earth2.analyze_patterns(params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("pattern analysis failure")
            raise JsonRpcError(500, "Pattern analysis failed", {"detail": str(exc)})

    tools.register(spec, handler)


def _register_stream_tool() -> None:
    spec = ToolSpec(
        name="stream_forecast_data",
        description="Open a server-sent stream for timeseries forecast data",
        input_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    )

    async def handler(params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await earth2.stream(params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("stream failure")
            raise JsonRpcError(500, "Stream failed", {"detail": str(exc)})

    tools.register(spec, handler)


_register_forecast_tool()
_register_visual_tool()
_register_patterns_tool()
_register_stream_tool()


# -----------------------------
# HTTP JSON-RPC endpoint (compatible with ChatGPT tool calling over HTTP)
# -----------------------------


@app.post("/rpc")
async def rpc_endpoint(req: Request) -> JSONResponse:
    payload: Dict[str, Any] | None = None
    try:
        payload = await req.json()
        if not isinstance(payload, dict):
            raise JsonRpcError(-32600, "Invalid Request: expected object")
        method, params, id_ = JsonRpc.parse(payload)
        result = await dispatch(method, params)
        return JSONResponse(JsonRpc.response(id_, result=result))
    except JsonRpcError as exc:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        return JSONResponse(JsonRpc.response(request_id, error=exc), status_code=400)
    except Exception as exc:  # pragma: no cover - final safeguard
        logger.exception("Unhandled error")
        err = JsonRpcError(-32603, "Internal error", {"detail": str(exc)})
        return JSONResponse(JsonRpc.response(None, error=err), status_code=500)


# -----------------------------
# WebSocket JSON-RPC (compatible with Claude MCP patterns)
# -----------------------------


class WSClient:
    """Wrapper storing websocket client metadata."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.id = str(uuid.uuid4())
        self.alive = True


clients: Dict[str, WSClient] = {}


@app.websocket("/ws")
async def ws_rpc(ws: WebSocket) -> None:
    await ws.accept()
    client = WSClient(ws)
    clients[client.id] = client
    logger.info("WS client connected: %s", client.id)
    try:
        while True:
            msg = await ws.receive_text()
            payload = json.loads(msg)
            try:
                if not isinstance(payload, dict):
                    raise JsonRpcError(-32600, "Invalid Request: expected object")
                method, params, id_ = JsonRpc.parse(payload)
                result = await dispatch(method, params)
                await ws.send_text(json.dumps(JsonRpc.response(id_, result=result)))
            except JsonRpcError as exc:
                await ws.send_text(json.dumps(JsonRpc.response(payload.get("id"), error=exc)))
    except WebSocketDisconnect:
        logger.info("WS client disconnected: %s", client.id)
    finally:
        clients.pop(client.id, None)


# -----------------------------
# Dispatcher for MCP methods
# -----------------------------


async def dispatch(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if method in ("mcp/initialize", "initialize"):
        return {
            "serverInfo": {
                "name": settings.MCP_SERVER_NAME,
                "version": settings.MCP_SERVER_VERSION,
            },
            "capabilities": {"tools": True, "resources": True, "experimental.stream": True},
        }
    if method in ("mcp/ping", "ping"):
        return {"ok": True, "ts": time.time()}
    if method in ("tools/list", "mcp/tools/list"):
        return {"tools": tools.list_specs()}
    if method in ("tools/call", "mcp/tools/call"):
        name = params.get("name") or params.get("tool")
        if not name:
            raise JsonRpcError(-32602, "Missing tool name: 'name'")
        args = params.get("arguments") or params.get("params") or {}
        if not isinstance(args, dict):
            raise JsonRpcError(-32602, "Invalid tool arguments")
        result = await tools.call(str(name), args)
        return {"content": result}
    if method in ("resources/list", "mcp/resources/list"):
        return {"resources": resources.list()}
    if method in ("resources/read", "mcp/resources/read"):
        uri = params.get("uri")
        if not uri:
            raise JsonRpcError(-32602, "Missing resource 'uri'")
        return resources.read(str(uri))
    if method == "resource://earth2/health":
        return await earth2.health()

    raise JsonRpcError(-32601, f"Method not found: {method}")
