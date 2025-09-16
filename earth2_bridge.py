"""Async client used by the MCP server to communicate with Earth-2 services."""
from __future__ import annotations

import logging
from typing import Any, Dict

import aiohttp

from config import settings


log = logging.getLogger("earth2")


class Earth2Error(RuntimeError):
    """Raised when the downstream Earth-2 service reports an error."""


class Earth2Client:
    """Wrapper around the internal Earth-2 REST endpoints."""

    def __init__(self) -> None:
        self.base = settings.EARTH2_BASE_URL.rstrip("/")
        self.token = settings.INTERNAL_API_TOKEN

    async def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise Earth2Error(f"GET {url} -> {resp.status}: {body}")
                return await resp.json()

    async def _post(self, path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=json_body, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise Earth2Error(f"POST {url} -> {resp.status}: {body}")
                return await resp.json()

    async def health(self) -> Dict[str, Any]:
        return await self._get(settings.EARTH2_HEALTH_PATH)

    async def generate_forecast(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "location": params["location"],
            "start_time": params["start_time"],
            "hours": params["hours"],
            "ngc_api_key": settings.NGC_API_KEY,
        }
        return await self._post(settings.EARTH2_FORECAST_PATH, payload)

    async def get_visual(self, request_id: str) -> Dict[str, Any]:
        return await self._get(f"/api/visual/{request_id}")

    async def analyze_patterns(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/api/analyze", params)

    async def stream(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # In real deployments, prefer SSE or websockets; returning a cursor here
        return await self._post(settings.EARTH2_STREAM_PATH, params)
