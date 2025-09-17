"""Shared utilities for building inputs and interacting with a FourCastNet NIM."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import requests

from earth2studio.data import ARCO
from earth2studio.models.px.sfno import VARIABLES

# FourCastNet expects 73 channels that match the VARIABLES ordering from earth2studio
CHANNELS: Iterable[str] = tuple(VARIABLES)
DEFAULT_INPUT_TIME = datetime(2023, 1, 1, tzinfo=timezone.utc)


def generate_input_array(input_time: datetime = DEFAULT_INPUT_TIME) -> np.ndarray:
    """Return a 73×721×1440 array wrapped in a batch dimension expected by the NIM."""
    ds = ARCO()
    da = ds(time=input_time, variable=VARIABLES)
    array = da.to_numpy().astype("float32", copy=False)
    if array.ndim != 3:
        raise ValueError(
            f"Expected a (variable, lat, lon) array from ARCO; received shape {array.shape}."
        )
    return array[None]


def write_input_array(output_path: Path | str, input_time: datetime = DEFAULT_INPUT_TIME) -> Path:
    """Generate an input array and persist it as ``.npy``."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, generate_input_array(input_time))
    return output


@dataclass(slots=True)
class NimConfig:
    """Connection information for a locally running FourCastNet NIM."""

    base_url: str = "http://localhost:8000"
    api_key: Optional[str] = None

    def headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def health_ready(config: NimConfig) -> None:
    """Raise ``HTTPError`` if the NIM is not ready."""
    url = f"{config.base_url.rstrip('/')}/v1/health/ready"
    resp = requests.get(url, headers=config.headers(), timeout=30)
    resp.raise_for_status()


def run_inference(
    *,
    config: NimConfig,
    input_path: Path | str,
    input_time: datetime,
    simulation_length: int,
    output_tar: Path | str,
) -> Path:
    """
    Send a forecast request and save the TAR archive returned by the NIM.

    Parameters
    ----------
    config:
        Connection and authentication information.
    input_path:
        ``.npy`` file created by :func:`write_input_array`.
    input_time:
        ISO-8601 timestamp matching the contents of ``input_path``.
    simulation_length:
        Number of forecast steps (each step is 6 hours).
    output_tar:
        Path where the TAR response will be written.
    """
    health_ready(config)

    url = f"{config.base_url.rstrip('/')}/v1/infer"
    payload = {
        "input_time": (None, input_time.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")),
        "simulation_length": (None, str(simulation_length)),
    }
    with Path(input_path).open("rb") as f_in:
        files = {"input_array": f_in, **payload}
        resp = requests.post(url, headers=config.headers(), files=files, timeout=300)
        resp.raise_for_status()

    output_path = Path(output_tar)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)
    return output_path
