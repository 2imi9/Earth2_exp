"""CLI helper that builds a FourCastNet input tensor from ARCO data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from fcn_client import DEFAULT_INPUT_TIME, write_input_array


def parse_time(value: str | None) -> datetime:
    if value is None:
        return DEFAULT_INPUT_TIME
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        default="fcn_inputs.npy",
        help="Path to the .npy file to create (default: fcn_inputs.npy)",
    )
    parser.add_argument(
        "--time",
        dest="input_time",
        default=None,
        help="ISO-8601 timestamp for the initial condition (default: 2023-01-01T00:00:00Z)",
    )
    args = parser.parse_args()

    input_time = parse_time(args.input_time)
    path = write_input_array(Path(args.output), input_time)
    print(f"Saved FourCastNet input tensor to {path} for {input_time.isoformat()}")


if __name__ == "__main__":
    main()
