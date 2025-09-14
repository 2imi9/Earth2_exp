#!/usr/bin/env python3
import glob
import numpy as np
import xarray as xr
import pandas as pd
from datetime import datetime, timedelta
from typing import Tuple, Optional

# ---- CONFIG you can change ----
INPUT_TIME_ISO = "2023-01-01T00:00:00Z"   # must match what you used in the /v1/infer call
STEP_HOURS = 6                             # FourCastNet NIM uses 6h steps by default
# --------------------------------

def _grid_lat_lon():
    # ERA5/FourCastNet grid: 721 × 1440 on 0.25° (lat +90→-90, lon 0→360)
    lat = np.linspace(90.0, -90.0, 721, dtype=np.float32)
    lon = np.linspace(0.0, 360.0 - 360.0/1440, 1440, dtype=np.float32)
    return lat, lon

def _load_dataset() -> xr.Dataset:
    """Load all forecast steps into an xarray Dataset, normalizing shapes."""
    steps = sorted(glob.glob("[0-9][0-9][0-9]_[0-9][0-9][0-9].npy"))
    if not steps:
        raise FileNotFoundError("No forecast step files like 000_000.npy found here.")

    # Build time coordinates (convert to numpy datetime64 once)
    t0 = datetime.fromisoformat(INPUT_TIME_ISO.replace("Z", "+00:00"))
    times_py = [t0 + timedelta(hours=STEP_HOURS * i) for i in range(len(steps))]
    times = np.array([np.datetime64(int(t.timestamp()), "s") for t in times_py])

    from earth2studio.models.px.sfno import VARIABLES
    lat, lon = _grid_lat_lon()

    norm_arrays = []
    for p in steps:
        arr = np.load(p)  # shape might be (73,721,1440) or (1,73,721,1440) or (1,1,73,721,1440), etc.
        arr = np.asarray(arr, dtype=np.float32)

        # 1) Squeeze any leading singleton dims (batch, time, etc.)
        while arr.ndim > 3 and arr.shape[0] == 1:
            arr = np.squeeze(arr, axis=0)

        # 2) Now expect 3 or 4 dims. If 4 with a singleton, drop it.
        if arr.ndim == 4 and 1 in arr.shape:
            arr = np.squeeze(arr)

        # 3) Ensure we ended up with exactly (73,721,1440) with channels first.
        if arr.ndim != 3:
            raise ValueError(f"Unexpected array shape {arr.shape} in {p}; expected 3D after squeeze.")

        if 73 not in arr.shape:
            raise ValueError(f"'73' (num variables) not found in shape {arr.shape} for {p}.")
        if arr.shape[0] != 73:
            ch_axis = list(arr.shape).index(73)
            arr = np.moveaxis(arr, ch_axis, 0)  # (73, H, W)

        if arr.shape[1:] != (721, 1440):
            raise ValueError(f"Spatial shape mismatch {arr.shape[1:]} in {p}; expected (721,1440).")

        norm_arrays.append(arr[np.newaxis, ...])  # add time axis: (1,73,721,1440)

    stack = np.concatenate(norm_arrays, axis=0)  # (T,73,721,1440)

    ds = xr.Dataset(
        {"fcn": (("time", "variable", "lat", "lon"), stack)},
        coords={"time": times, "variable": VARIABLES, "lat": lat, "lon": lon},
        attrs={"description": "FourCastNet forecast"}
    )
    return ds

def _wrap_lon_east(lon_deg: float) -> float:
    """Convert [-180,180] to [0,360)."""
    return lon_deg % 360.0

def _bilinear_on_regular_grid(field2d: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                              lat_q: float, lon_q: float) -> float:
    """
    Bilinear interpolation on a regular (lat descending, lon ascending) grid.
    field2d: (lat, lon)
    """
    # indices around the query point
    lat_idx = np.searchsorted(lat[::-1], lat_q, side="left")
    lat0 = len(lat) - 1 - np.clip(lat_idx, 1, len(lat) - 1)
    lat1 = np.clip(lat0 + 1, 0, len(lat) - 1)

    lon_q = _wrap_lon_east(lon_q)
    j = np.searchsorted(lon, lon_q, side="right") - 1
    lon0 = j % len(lon)
    lon1 = (j + 1) % len(lon)

    # weights
    y0, y1 = lat[lat0], lat[lat1]
    x0, x1 = lon[lon0], lon[lon1]
    wy = 0.0 if y0 == y1 else (y0 - lat_q) / (y0 - y1)  # latitude axis is decreasing
    wx = 0.0 if x0 == x1 else (lon_q - x0) / ((x1 - x0) if x1 > x0 else ((x1 + 360) - x0))

    # neighbor values
    f00 = field2d[lat0, lon0]
    f01 = field2d[lat0, lon1]
    f10 = field2d[lat1, lon0]
    f11 = field2d[lat1, lon1]

    return (1 - wy) * ((1 - wx) * f00 + wx * f01) + wy * ((1 - wx) * f10 + wx * f11)

def _local_stats_3x3(field2d: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                     lat_q: float, lon_q: float) -> Tuple[float, float, float]:
    """Mean/min/max over a 3×3 neighborhood around nearest grid cell (fast context)."""
    i = np.argmin(np.abs(lat - lat_q))
    j = np.argmin(np.abs((lon - _wrap_lon_east(lon_q) + 180) % 360 - 180))
    ii = np.clip(np.array([i - 1, i, i + 1]), 0, len(lat) - 1)
    jj = (np.array([j - 1, j, j + 1]) % len(lon))
    block = field2d[np.ix_(ii, jj)]
    return float(block.mean()), float(block.min()), float(block.max())

def point_timeseries(lat_q: float, lon_q: float,
                     want_context: bool = True,
                     ds: Optional[xr.Dataset] = None) -> pd.DataFrame:
    """
    Return a DataFrame with:
      - time (ISO)
      - t2m_C (2m temperature in °C)
      - tcwv_kg_m2 (total column water vapour)
      - ws10m_m_s (10 m wind speed, m/s)
      - msl_hPa (mean sea-level pressure, hPa)
    Plus optional 3×3 neighborhood stats for t2m, tcwv, ws10m, msl.
    """
    if ds is None:
        ds = _load_dataset()

    # variable indices (do this once)
    varnames = ds["variable"].values
    def vidx(name: str) -> int:
        idx = np.where(varnames == name)[0]
        if len(idx) == 0:
            raise KeyError(f"Variable '{name}' not found in dataset variables.")
        return int(idx[0])

    i_t2m  = vidx("t2m")
    i_tcwv = vidx("tcwv")
    i_u10m = vidx("u10m")
    i_v10m = vidx("v10m")
    i_msl  = vidx("msl")

    lat = ds["lat"].values
    lon = ds["lon"].values

    rows = []
    for t_idx, t in enumerate(ds["time"].values):
        F = ds["fcn"].isel(time=t_idx)

        # Interpolate point values
        t2mK  = _bilinear_on_regular_grid(F.isel(variable=i_t2m).values,  lat, lon, lat_q, lon_q)
        tcwv  = _bilinear_on_regular_grid(F.isel(variable=i_tcwv).values, lat, lon, lat_q, lon_q)
        u10   = _bilinear_on_regular_grid(F.isel(variable=i_u10m).values, lat, lon, lat_q, lon_q)
        v10   = _bilinear_on_regular_grid(F.isel(variable=i_v10m).values, lat, lon, lat_q, lon_q)
        mslPa = _bilinear_on_regular_grid(F.isel(variable=i_msl).values,  lat, lon, lat_q, lon_q)

        ws10 = float(np.hypot(u10, v10))
        msl_hPa = float(mslPa / 100.0)

        t_iso = np.datetime_as_string(t, unit="s")  # times are numpy datetime64[s]

        rec = {
            "time": t_iso,
            "t2m_C": float(t2mK - 273.15),
            "tcwv_kg_m2": float(tcwv),
            "ws10m_m_s": ws10,
            "msl_hPa": msl_hPa,
        }

        if want_context:
            # Neighborhood stats for each requested field
            meanC,  minC,  maxC  = _local_stats_3x3(F.isel(variable=i_t2m).values,  lat, lon, lat_q, lon_q)
            meanWV, minWV, maxWV = _local_stats_3x3(F.isel(variable=i_tcwv).values, lat, lon, lat_q, lon_q)
            # Build a wind speed field for neighborhood context
            ufield = F.isel(variable=i_u10m).values
            vfield = F.isel(variable=i_v10m).values
            wsfield = np.hypot(ufield, vfield)
            meanWS, minWS, maxWS = _local_stats_3x3(wsfield, lat, lon, lat_q, lon_q)
            meanMSL, minMSL, maxMSL = _local_stats_3x3(F.isel(variable=i_msl).values, lat, lon, lat_q, lon_q)

            rec.update({
                "t2m_C_neigh_mean":  meanC - 273.15,
                "t2m_C_neigh_min":   minC - 273.15,
                "t2m_C_neigh_max":   maxC - 273.15,
                "tcwv_neigh_mean":   meanWV,
                "tcwv_neigh_min":    minWV,
                "tcwv_neigh_max":    maxWV,
                "ws10m_neigh_mean":  float(meanWS),
                "ws10m_neigh_min":   float(minWS),
                "ws10m_neigh_max":   float(maxWS),
                "msl_hPa_neigh_mean": float(meanMSL / 100.0),
                "msl_hPa_neigh_min":  float(minMSL / 100.0),
                "msl_hPa_neigh_max":  float(maxMSL / 100.0),
            })

        rows.append(rec)

    df = pd.DataFrame(rows)
    return df

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Point stats from FourCastNet forecast outputs")
    p.add_argument("--lat", type=float, required=True, help="Latitude in degrees [-90, 90]")
    p.add_argument("--lon", type=float, required=True, help="Longitude in degrees (either -180..180 or 0..360)")
    p.add_argument("--no-context", action="store_true", help="Disable 3x3 neighborhood stats")
    p.add_argument("--csv", type=str, default="point_stats.csv", help="Output CSV filename")
    args = p.parse_args()

    ds = _load_dataset()
    df = point_timeseries(args.lat, args.lon, want_context=(not args.no_context), ds=ds)
    df.to_csv(args.csv, index=False)
    print(f"Wrote {args.csv} with {len(df)} rows and {len(df.columns)} columns → {args.csv}")
