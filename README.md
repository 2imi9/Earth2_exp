# FourCastNet NIM Toolkit

Utilities for preparing inputs, querying an Earth-2 FourCastNet NIM, and post-processing the forecasts live in [`fourcastnet-nim/`](fourcastnet-nim/).

## Repository layout

| Path | Purpose |
| --- | --- |
| [`fourcastnet-nim/fcn_client.py`](fourcastnet-nim/fcn_client.py) | Shared helpers for creating input tensors and interacting with a running NIM instance. |
| [`fourcastnet-nim/make_input.py`](fourcastnet-nim/make_input.py) | Command-line interface that writes the initial-condition tensor used by the NIM. |
| [`fourcastnet-nim/query_nim.py`](fourcastnet-nim/query_nim.py) | CLI that submits a forecast request and stores the returned TAR archive. |
| [`fourcastnet-nim/point_stats.py`](fourcastnet-nim/point_stats.py) | Extract a point time-series (with optional neighborhood stats) from the forecasted `.npy` files. |
| [`fourcastnet-nim/requirements.txt`](fourcastnet-nim/requirements.txt) | Python dependencies needed for the utilities. |
| [`fourcastnet-nim/Dockerfile`](fourcastnet-nim/Dockerfile) | Minimal image that installs the dependencies and exposes a shell for manual commands. |
| [`docker-compose.yml`](docker-compose.yml) | Convenience wrapper to build/run the image locally. |

## Prerequisites

* Python 3.10+
* Access to the Earth-2 `earth2studio` data source (shipped in the requirements file)
* A running FourCastNet NIM instance reachable from your machine
* (Optional) Docker & Docker Compose if you prefer containerized workflows

Install the Python requirements into your environment of choice:

```bash
pip install -r fourcastnet-nim/requirements.txt
```

## Quickstart workflow

The utilities are designed to be run from the repository root using the system Python. Each step builds on the previous one.

1. **Create the NIM input tensor**

   ```bash
   python fourcastnet-nim/make_input.py --time 2023-01-01T00:00:00Z --output inputs/fcn_inputs.npy
   ```

   This command samples the ARCO dataset for the requested analysis time and writes a batchified `(1, 73, 721, 1440)` tensor that FourCastNet expects.

2. **Send the forecast request**

   ```bash
   python fourcastnet-nim/query_nim.py \
       --base-url http://localhost:8000 \
       --input inputs/fcn_inputs.npy \
       --time 2023-01-01T00:00:00Z \
       --steps 4 \
       --output outputs/fcn_forecast.tar
   ```

   The script verifies that the `/v1/health/ready` endpoint is reachable, submits the request, and saves the returned TAR archive.

3. **Extract the forecasted arrays**

   FourCastNet returns its forecast as a TAR archive containing files named `000_000.npy`, `000_001.npy`, etc. Extract them into a working directory before running any diagnostics:

   ```bash
   mkdir -p outputs/fcn_forecast
   tar -xvf outputs/fcn_forecast.tar -C outputs/fcn_forecast
   cd outputs/fcn_forecast
   ```

4. **Compute point statistics**

   With the `.npy` files available in the current directory, request a point time-series (e.g., Cape Town):

   ```bash
   python ../../fourcastnet-nim/point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv
   ```

   By default the script calculates 2 m temperature, total column water vapor, 10 m wind, and mean sea-level pressure along with 3×3 neighborhood statistics. Use `--when <timestamp>` with `--interp linear` if you need a single time slice.

## Running inside Docker

The Docker image installs the Python dependencies and leaves you at a shell prompt.

```bash
docker build -t fourcastnet-client fourcastnet-nim
docker run --rm -it -v "$(pwd)":/workspace fourcastnet-client /bin/bash
```

From inside the container, follow the quickstart steps (the project lives in `/workspace`). If you prefer Docker Compose, populate `fourcastnet-nim/.env` with your `NIM_API_KEY` and run:

```bash
docker compose up --build -d
docker compose exec fourcastnet python query_nim.py --input fcn_inputs.npy
```

## Development checks

Linting is not configured; however, Python's bytecode compiler helps catch syntax issues:

```bash
python -m py_compile fourcastnet-nim/*.py
```

Run this after modifying any scripts to ensure the project remains importable.
