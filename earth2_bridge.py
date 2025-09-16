import logging
from typing import Any, Dict

import aiohttp

from config import settings

log = logging.getLogger("earth2")


class Earth2Error(RuntimeError):
    """Raised when the Earth-2 service responds with an error."""


class Earth2Client:
    """Async client that brokers calls to the downstream Earth-2 service."""

    def __init__(self) -> None:
        self.base = settings.EARTH2_BASE_URL.rstrip("/")
        self.token = settings.INTERNAL_API_TOKEN

    async def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise Earth2Error(f"GET {url} -> {response.status}: {body}")
                return await response.json()

    async def _post(self, path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=json_body, headers=headers) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise Earth2Error(f"POST {url} -> {response.status}: {body}")
                return await response.json()

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
        return await self._post(settings.EARTH2_STREAM_PATH, params)
