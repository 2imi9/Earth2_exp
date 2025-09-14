# FourCastNet NIM Client

This repository bundles utilities for querying Earth-2 FourCastNet forecasts. All code lives in the `fourcastnet-nim` directory.

## Features

- **`fourcastnet-nim/point_stats.py`** – extract time-series forecasts at any latitude/longitude with optional neighborhood context and temporal interpolation.
  - Variables: 2 m temperature (`t2m_C`), total column water vapor (`tcwv_kg_m2`), 10 m wind speed (`ws10m_m_s`), mean sea-level pressure (`msl_hPa`).
  - Supports 3×3 neighborhood summaries (mean/min/max) and arbitrary time requests using nearest or linear interpolation.
- **`fourcastnet-nim/query_nim.py`** – simple `requests`-based example for sending an input array to a local FourCastNet NIM and saving the forecast output.
- **Manual-friendly Docker setup** – the image installs required system and Python packages and stays idle so you can run any script manually.

## Building
The `fourcastnet-nim/Dockerfile` installs all dependencies on top of a lightweight Python base image. Build it with:

```bash
docker build -t fourcastnet-client fourcastnet-nim
```

## Running
You can run the client either with Docker Compose or by invoking the container directly.

### Docker Compose
1. Create a file at `fourcastnet-nim/.env` containing your NIM API key:

   ```bash
   echo "NIM_API_KEY=your_key_here" > fourcastnet-nim/.env
   ```

2. Build and start the container:

   ```bash
   docker compose up --build -d
   ```

3. Run whatever script you need inside the container, for example the point statistics utility:

   ```bash
   docker compose exec fourcastnet python point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv
   ```

### Manual Docker
All project scripts are placed in `/opt/nim` inside the image. To run the point statistics utility without Docker Compose, mount any required data and run the container:

```bash
docker run --rm fourcastnet-client python point_stats.py --lat -33.93 --lon 18.42 --csv cape_town.csv
```

## Development
Ensure code changes compile:

```bash
python -m py_compile fourcastnet-nim/make_input.py fourcastnet-nim/point_stats.py fourcastnet-nim/query_nim.py
```
