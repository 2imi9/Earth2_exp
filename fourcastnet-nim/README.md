# FourCastNet NIM Client

This repository bundles utilities for querying Earth-2 FourCastNet forecasts and exposing them through a small Gradio interface backed by vLLM.

## Features

- **`point_stats.py`** – extract time-series forecasts at any latitude/longitude with optional neighborhood context and temporal interpolation.
  - Variables: 2 m temperature (`t2m_C`), total column water vapor (`tcwv_kg_m2`), 10 m wind speed (`ws10m_m_s`), mean sea-level pressure (`msl_hPa`).
  - Supports 3×3 neighborhood summaries (mean/min/max) and arbitrary time requests using nearest or linear interpolation.
- **`app.py`** – Gradio UI that uses `gpt-oss-20b` via vLLM to answer environmental questions for a given location.
- **Offline-friendly Docker build** – dependencies are downloaded in a builder stage and installed from a local wheelhouse so the runtime image needs no internet access.

## Building
The provided `client.Dockerfile` performs a multi-stage build. The first stage downloads the Python wheels using internet access, while the second stage installs them offline.

```bash
docker build -f client.Dockerfile -t fourcastnet-client .
```

## Running
All project scripts are placed in `/opt/nim` inside the image. To generate FourCastNet inputs or launch the Gradio app, mount any required data and run the container:

```bash
docker run --rm -p 7860:7860 fourcastnet-client python app.py
```

To run the point statistics utility directly:

```bash
docker run --rm fourcastnet-client python point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv
```

## Development
Ensure code changes compile:

```bash
python -m py_compile make_input.py app.py point_stats.py
```
