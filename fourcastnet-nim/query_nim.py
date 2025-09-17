"""Submit a forecast request to a locally running FourCastNet NIM."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from fcn_client import DEFAULT_INPUT_TIME, NimConfig, run_inference


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
        "--base-url",
        default="http://localhost:8000",
        help="Base URL where the NIM is exposed (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key for authenticated deployments",
    )
    parser.add_argument(
        "--input",
        default="fcn_inputs.npy",
        help="Path to the .npy file created via make_input.py (default: fcn_inputs.npy)",
    )
    parser.add_argument(
        "--time",
        dest="input_time",
        default=None,
        help="ISO-8601 timestamp matching the contents of --input",
    )
    parser.add_argument(
        "--steps",
        dest="simulation_length",
        type=int,
        default=4,
        help="Number of 6-hour steps to request (default: 4)",
    )
    parser.add_argument(
        "--output",
        default="output.tar",
        help="Where to store the TAR archive returned by the NIM (default: output.tar)",
    )
    args = parser.parse_args()

    config = NimConfig(base_url=args.base_url, api_key=args.api_key)
    input_time = parse_time(args.input_time)
    output = run_inference(
        config=config,
        input_path=Path(args.input),
        input_time=input_time,
        simulation_length=args.simulation_length,
        output_tar=Path(args.output),
    )
    print(
        "Saved forecast to",
        output,
        "for initial condition",
        input_time.isoformat().replace("+00:00", "Z"),
    )


if __name__ == "__main__":
    main()
