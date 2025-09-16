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
from earth2_bridge import Earth2Client, Earth2Error

logger = logging.getLogger("mcp")
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

app = FastAPI(title=settings.MCP_SERVER_NAME, version=settings.MCP_SERVER_VERSION)


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


class JsonRpc:
    @staticmethod
    def response(id_: Any, result: Any = None, error: Optional["JsonRpcError"] = None) -> Dict[str, Any]:
        if error:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": error.code, "message": str(error), "data": error.data},
            }
        return {"jsonrpc": "2.0", "id": id_, "result": result}

    @staticmethod
    def parse(payload: Any) -> tuple[str, Dict[str, Any], Any]:
        if not isinstance(payload, dict):
            raise JsonRpcError(-32600, "Invalid Request: body must be an object")
        if payload.get("jsonrpc") != "2.0":
            raise JsonRpcError(-32600, "Invalid Request: jsonrpc must be '2.0'")
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            raise JsonRpcError(-32600, "Invalid Request: missing method")
        params = payload.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "Invalid params: expected an object")
        return method, params, payload.get("id")


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
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolFunc] = {}

    def register(self, spec: ToolSpec, handler: ToolFunc) -> None:
        self._tools[spec.name] = spec
        self._handlers[spec.name] = handler
        logger.info("Registered tool %s", spec.name)

    def list_specs(self) -> List[Dict[str, Any]]:
        return [tool.model_dump() for tool in self._tools.values()]

    async def call(self, name: str, params: Dict[str, Any]) -> Any:
        if name not in self._handlers:
            raise JsonRpcError(-32601, f"Tool not found: {name}")
        handler = self._handlers[name]
        if asyncio.iscoroutinefunction(handler):
            return await handler(params)
        return handler(params)


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: Dict[str, Resource] = {}

    def add(self, resource: Resource) -> None:
        self._resources[resource.uri] = resource

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
        }


tools = ToolRegistry()
resources = ResourceRegistry()
earth2 = Earth2Client()

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


def _require_params(params: Dict[str, Any], required: List[str]) -> None:
    missing = [key for key in required if key not in params]
    if missing:
        raise JsonRpcError(-32602, f"Missing parameters: {', '.join(missing)}")


async def _generate_weather_forecast(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_params(params, ["location", "start_time", "hours"])
    try:
        return await earth2.generate_forecast(params)
    except Earth2Error as exc:  # pragma: no cover - network failure path
        logger.exception("forecast failure")
        raise JsonRpcError(500, "Forecast failed", {"detail": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected forecast failure")
        raise JsonRpcError(500, "Forecast failed", {"detail": str(exc)}) from exc


def _forecast_spec() -> ToolSpec:
    return ToolSpec(
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


def _visual_spec() -> ToolSpec:
    return ToolSpec(
        name="get_forecast_visualization",
        description="Render forecast visualization (PNG) for a request id",
        input_schema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    )


def _pattern_spec() -> ToolSpec:
    return ToolSpec(
        name="analyze_weather_patterns",
        description="Analyze ERA5/Earth-2 outputs for trends/anomalies",
        input_schema={
            "type": "object",
            "properties": {"bbox": {"type": "array"}},
            "required": ["bbox"],
        },
    )


def _stream_spec() -> ToolSpec:
    return ToolSpec(
        name="stream_forecast_data",
        description="Open a server-sent stream for timeseries forecast data",
        input_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    )


async def _get_forecast_visualization(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_params(params, ["request_id"])
    try:
        return await earth2.get_visual(params["request_id"])
    except Earth2Error as exc:  # pragma: no cover - network failure path
        logger.exception("visualization failure")
        raise JsonRpcError(500, "Visualization failed", {"detail": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected visualization failure")
        raise JsonRpcError(500, "Visualization failed", {"detail": str(exc)}) from exc


async def _analyze_weather_patterns(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_params(params, ["bbox"])
    try:
        return await earth2.analyze_patterns(params)
    except Earth2Error as exc:  # pragma: no cover
        raise JsonRpcError(500, "Pattern analysis failed", {"detail": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        raise JsonRpcError(500, "Pattern analysis failed", {"detail": str(exc)}) from exc


async def _stream_forecast_data(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_params(params, ["location"])
    try:
        return await earth2.stream(params)
    except Earth2Error as exc:  # pragma: no cover
        raise JsonRpcError(500, "Stream failed", {"detail": str(exc)}) from exc
    except Exception as exc:  # pragma: no cover
        raise JsonRpcError(500, "Stream failed", {"detail": str(exc)}) from exc


tools.register(_forecast_spec(), _generate_weather_forecast)
tools.register(_visual_spec(), _get_forecast_visualization)
tools.register(_pattern_spec(), _analyze_weather_patterns)
tools.register(_stream_spec(), _stream_forecast_data)


class WSClient:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.id = str(uuid.uuid4())
        self.alive = True


clients: Dict[str, WSClient] = {}


@app.post("/rpc")
async def rpc_endpoint(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:  # pragma: no cover - FastAPI already validates JSON
        err = JsonRpcError(-32700, "Parse error", {"detail": str(exc)})
        return JSONResponse(JsonRpc.response(None, error=err), status_code=400)

    try:
        method, params, id_ = JsonRpc.parse(payload)
        result = await dispatch(method, params)
        return JSONResponse(JsonRpc.response(id_, result=result))
    except JsonRpcError as exc:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        status = 500 if exc.code >= 500 else 400
        return JSONResponse(JsonRpc.response(request_id, error=exc), status_code=status)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unhandled error")
        request_id = payload.get("id") if isinstance(payload, dict) else None
        err = JsonRpcError(-32603, "Internal error", {"detail": str(exc)})
        return JSONResponse(JsonRpc.response(request_id, error=err), status_code=500)


@app.websocket("/ws")
async def ws_rpc(ws: WebSocket) -> None:
    await ws.accept()
    client = WSClient(ws)
    clients[client.id] = client
    logger.info("WS client connected: %s", client.id)
    try:
        while True:
            message = await ws.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps(JsonRpc.response(None, error=JsonRpcError(-32700, "Parse error"))))
                continue
            try:
                method, params, id_ = JsonRpc.parse(payload)
                result = await dispatch(method, params)
                await ws.send_text(json.dumps(JsonRpc.response(id_, result=result)))
            except JsonRpcError as exc:
                await ws.send_text(json.dumps(JsonRpc.response(payload.get("id"), error=exc)))
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Unhandled WS error")
                err = JsonRpcError(-32603, "Internal error", {"detail": str(exc)})
                await ws.send_text(json.dumps(JsonRpc.response(payload.get("id"), error=err)))
    except WebSocketDisconnect:
        logger.info("WS client disconnected: %s", client.id)
    finally:
        clients.pop(client.id, None)


async def dispatch(method: str, params: Dict[str, Any]) -> Dict[str, Any] | Any:
    if method in ("mcp/initialize", "initialize"):
        return {
            "serverInfo": {"name": settings.MCP_SERVER_NAME, "version": settings.MCP_SERVER_VERSION},
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
        arguments = params.get("arguments") or params.get("params") or {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "Invalid params: expected object for arguments")
        result = await tools.call(name, arguments)
        return {"content": result}
    if method in ("resources/list", "mcp/resources/list"):
        return {"resources": resources.list()}
    if method in ("resources/read", "mcp/resources/read"):
        uri = params.get("uri")
        if not uri:
            raise JsonRpcError(-32602, "Missing resource 'uri'")
        return resources.read(uri)
    if method == "resource://earth2/health":
        try:
            return await earth2.health()
        except Earth2Error as exc:  # pragma: no cover
            raise JsonRpcError(500, "Health check failed", {"detail": str(exc)}) from exc
        except Exception as exc:  # pragma: no cover
            raise JsonRpcError(500, "Health check failed", {"detail": str(exc)}) from exc

    raise JsonRpcError(-32601, f"Method not found: {method}")
