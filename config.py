"""Application configuration powered by Pydantic settings."""
from __future__ import annotations

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    MCP_SERVER_NAME: str = "earth2-mcp"
    MCP_SERVER_VERSION: str = "1.0.0"

    EARTH2_BASE_URL: str = "http://earth_2_fourcastnet:8000"
    EARTH2_HEALTH_PATH: str = "/health"
    EARTH2_FORECAST_PATH: str = "/api/forecast"
    EARTH2_STREAM_PATH: str = "/api/forecast/stream"

    NGC_API_KEY: str = Field(default="", description="NGC access token")
    INTERNAL_API_TOKEN: str = ""

    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
