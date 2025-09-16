"""Small helper around docker SDK for optional container orchestration."""
from __future__ import annotations

import logging
from typing import Optional

try:  # pragma: no cover - docker optional during tests
    import docker  # type: ignore
except Exception:  # pragma: no cover - fall back when docker not installed
    docker = None


log = logging.getLogger("dock")


class DockerManager:
    """Wrapper providing start/stop helpers using docker SDK."""

    def __init__(self) -> None:
        if docker is None:
            raise RuntimeError("docker SDK not installed. pip install docker")
        self.client = docker.from_env()

    def start(self, name: str) -> str:
        try:
            container = self.client.containers.get(name)
            container.start()
            return "started"
        except Exception as exc:  # pragma: no cover - runtime logging only
            log.exception("start failed")
            raise exc

    def stop(self, name: str) -> str:
        try:
            container = self.client.containers.get(name)
            container.stop(timeout=15)
            return "stopped"
        except Exception as exc:  # pragma: no cover - runtime logging only
            log.exception("stop failed")
            raise exc

    def inspect(self, name: str) -> Optional[dict]:
        try:
            container = self.client.containers.get(name)
            return container.attrs
        except Exception:  # pragma: no cover - inspection best-effort
            return None
