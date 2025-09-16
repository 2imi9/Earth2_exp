import logging
from typing import Optional

try:
    import docker  # type: ignore
except Exception:  # pragma: no cover
    docker = None

log = logging.getLogger("dock")


class DockerManager:
    def __init__(self) -> None:
        if docker is None:
            raise RuntimeError("docker SDK not installed. pip install docker")
        self.client = docker.from_env()

    def start(self, name: str) -> str:
        try:
            container = self.client.containers.get(name)
            container.start()
            return "started"
        except Exception:
            log.exception("start failed")
            raise

    def stop(self, name: str) -> str:
        try:
            container = self.client.containers.get(name)
            container.stop(timeout=15)
            return "stopped"
        except Exception:
            log.exception("stop failed")
            raise

    def inspect(self, name: str) -> Optional[dict]:
        try:
            container = self.client.containers.get(name)
            return container.attrs
        except Exception:
            return None
