#!/usr/bin/env python3
import glob
import numpy as np
import xarray as xr
import pandas as pd
from datetime import datetime, timedelta
from typing import Tuple, Optional

from fcn_client import CHANNELS

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

    # Build time coordinates (as numpy datetime64[s] without tz parsing warnings)
    t0 = datetime.fromisoformat(INPUT_TIME_ISO.replace("Z", "+00:00"))
    times_py = [t0 + timedelta(hours=STEP_HOURS * i) for i in range(len(steps))]
    times = np.array([np.datetime64(int(t.timestamp()), "s") for t in times_py])

    lat, lon = _grid_lat_lon()

    norm_arrays = []
    for p in steps:
        arr = np.load(p)  # could be (73,721,1440) or have leading singletons
        arr = np.asarray(arr, dtype=np.float32)

        # squeeze leading singleton dims (batch, time, etc.)
        while arr.ndim > 3 and arr.shape[0] == 1:
            arr = np.squeeze(arr, axis=0)

        # drop any leftover singleton if 4D
        if arr.ndim == 4 and 1 in arr.shape:
            arr = np.squeeze(arr)

        if arr.ndim != 3:
            raise ValueError(f"Unexpected array shape {arr.shape} in {p}; expected 3D after squeeze.")

        if 73 not in arr.shape:
            raise ValueError(f"'73' (num variables) not found in shape {arr.shape} for {p}.")
        if arr.shape[0] != 73:
            ch_axis = list(arr.shape).index(73)
            arr = np.moveaxis(arr, ch_axis, 0)  # (73, H, W)

        if arr.shape[1:] != (721, 1440):
            raise ValueError(f"Spatial shape mismatch {arr.shape[1:]} in {p}; expected (721,1440).")

        norm_arrays.append(arr[np.newaxis, ...])  # (1,73,721,1440)

    stack = np.concatenate(norm_arrays, axis=0)  # (T,73,721,1440)

    ds = xr.Dataset(
        {"fcn": (("time", "variable", "lat", "lon"), stack)},
        coords={"time": times, "variable": CHANNELS, "lat": lat, "lon": lon},
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
    wy = 0.0 if y0 == y1 else (y0 - lat_q) / (y0 - y1)  # latitude axis decreases
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

def _time_indices_for_linear(times: np.ndarray, when: np.datetime64) -> Tuple[int, int, float]:
    """
    Given monotonically increasing times (datetime64[s]) and a query `when`,
    return (i0, i1, alpha) such that value_at_when = (1-alpha)*v[i0] + alpha*v[i1].
    If `when` equals a time exactly, returns (i, i, 0.0).
    """
    if when <= times[0]:
        return 0, 0, 0.0
    if when >= times[-1]:
        return len(times) - 1, len(times) - 1, 0.0
    # find the right bracket
    i1 = int(np.searchsorted(times, when, side="right"))
    i0 = i1 - 1
    t0 = times[i0].astype("datetime64[s]").astype("int64")
    t1 = times[i1].astype("datetime64[s]").astype("int64")
    tw = when.astype("datetime64[s]").astype("int64")
    alpha = 0.0 if t1 == t0 else (tw - t0) / (t1 - t0)
    return i0, i1, float(alpha)

def _row_from_time_index(ds: xr.Dataset, t_idx: int, lat_q: float, lon_q: float,
                         want_context: bool, cache_vars=None) -> dict:
    """Compute a row (no time interpolation): interpolate space at a single time index."""
    if cache_vars is None:
        cache_vars = {}
    varnames = ds["variable"].values

    def vidx(name: str) -> int:
        key = f"vidx:{name}"
        if key in cache_vars:
            return cache_vars[key]
        idx = np.where(varnames == name)[0]
        if len(idx) == 0:
            raise KeyError(f"Variable '{name}' not found.")
        cache_vars[key] = int(idx[0])
        return cache_vars[key]

    i_t2m  = vidx("t2m")
    i_tcwv = vidx("tcwv")
    i_u10m = vidx("u10m")
    i_v10m = vidx("v10m")
    i_msl  = vidx("msl")

    lat = ds["lat"].values
    lon = ds["lon"].values

    F = ds["fcn"].isel(time=t_idx)
    # point interpolations
    t2mK  = _bilinear_on_regular_grid(F.isel(variable=i_t2m).values,  lat, lon, lat_q, lon_q)
    tcwv  = _bilinear_on_regular_grid(F.isel(variable=i_tcwv).values, lat, lon, lat_q, lon_q)
    u10   = _bilinear_on_regular_grid(F.isel(variable=i_u10m).values, lat, lon, lat_q, lon_q)
    v10   = _bilinear_on_regular_grid(F.isel(variable=i_v10m).values, lat, lon, lat_q, lon_q)
    mslPa = _bilinear_on_regular_grid(F.isel(variable=i_msl).values,  lat, lon, lat_q, lon_q)

    ws10 = float(np.hypot(u10, v10))
    msl_hPa = float(mslPa / 100.0)

    t_iso = np.datetime_as_string(ds["time"].values[t_idx], unit="s")

    rec = {
        "time": t_iso,
        "t2m_C": float(t2mK - 273.15),
        "tcwv_kg_m2": float(tcwv),
        "ws10m_m_s": ws10,
        "msl_hPa": msl_hPa,
    }

    if want_context:
        # Neighborhood stats (fast, nearest-step only)
        meanC,  minC,  maxC  = _local_stats_3x3(F.isel(variable=i_t2m).values,  lat, lon, lat_q, lon_q)
        meanWV, minWV, maxWV = _local_stats_3x3(F.isel(variable=i_tcwv).values, lat, lon, lat_q, lon_q)
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

    return rec

def point_timeseries(lat_q: float, lon_q: float,
                     want_context: bool = True,
                     ds: Optional[xr.Dataset] = None) -> pd.DataFrame:
    """Full time series (all available steps)."""
    if ds is None:
        ds = _load_dataset()

    rows = []
    cache_vars = {}
    for t_idx in range(ds.sizes["time"]):
        rows.append(_row_from_time_index(ds, t_idx, lat_q, lon_q, want_context, cache_vars))
    return pd.DataFrame(rows)

def point_at_time(lat_q: float, lon_q: float, when_iso: str,
                  interp: str = "nearest",
                  want_context: bool = True,
                  ds: Optional[xr.Dataset] = None) -> pd.DataFrame:
    """
    Single-row result at a requested time.
    - interp='nearest': pick closest step.
    - interp='linear' : linear in time between bracketing steps (u/v blended correctly).
      Context stats are taken from the nearest step.
    """
    if ds is None:
        ds = _load_dataset()

    # parse when
    if when_iso.endswith("Z"):
        when_iso = when_iso.replace("Z", "+00:00")
    when_dt = datetime.fromisoformat(when_iso)
    when_np = np.datetime64(int(when_dt.timestamp()), "s")

    times = ds["time"].values.astype("datetime64[s]")

    if interp == "nearest":
        idx = int(np.argmin(np.abs(times - when_np)))
        row = _row_from_time_index(ds, idx, lat_q, lon_q, want_context)
        # annotate which step was chosen
        row["time_requested"] = np.datetime_as_string(when_np, unit="s")
        row["time_interp"] = "nearest"
        return pd.DataFrame([row])

    if interp == "linear":
        i0, i1, alpha = _time_indices_for_linear(times, when_np)
        # if exact match, fall back to nearest
        if i0 == i1:
            row = _row_from_time_index(ds, i0, lat_q, lon_q, want_context)
            row["time_requested"] = np.datetime_as_string(when_np, unit="s")
            row["time_interp"] = "exact"
            return pd.DataFrame([row])

        # interpolate scalars in time: do space bilinear at both times, then time-blend
        varnames = ds["variable"].values
        def vidx(name: str) -> int:
            idx = np.where(varnames == name)[0]
            if len(idx) == 0:
                raise KeyError(f"Variable '{name}' not found.")
            return int(idx[0])

        i_t2m, i_tcwv = vidx("t2m"), vidx("tcwv")
        i_u10m, i_v10m = vidx("u10m"), vidx("v10m")
        i_msl = vidx("msl")

        lat = ds["lat"].values
        lon = ds["lon"].values

        F0 = ds["fcn"].isel(time=i0)
        F1 = ds["fcn"].isel(time=i1)

        def interp_point(var_idx):
            v0 = _bilinear_on_regular_grid(F0.isel(variable=var_idx).values, lat, lon, lat_q, lon_q)
            v1 = _bilinear_on_regular_grid(F1.isel(variable=var_idx).values, lat, lon, lat_q, lon_q)
            return (1.0 - alpha) * v0 + alpha * v1

        t2mK  = interp_point(i_t2m)
        tcwv  = interp_point(i_tcwv)
        u10   = interp_point(i_u10m)
        v10   = interp_point(i_v10m)
        mslPa = interp_point(i_msl)

        ws10 = float(np.hypot(u10, v10))
        msl_hPa = float(mslPa / 100.0)

        rec = {
            "time": np.datetime_as_string(when_np, unit="s"),
            "t2m_C": float(t2mK - 273.15),
            "tcwv_kg_m2": float(tcwv),
            "ws10m_m_s": ws10,
            "msl_hPa": msl_hPa,
            "time_requested": np.datetime_as_string(when_np, unit="s"),
            "time_interp": "linear",
            "alpha": alpha,
            "t0": np.datetime_as_string(times[i0], unit="s"),
            "t1": np.datetime_as_string(times[i1], unit="s"),
        }

        if want_context:
            # context from nearest step to 'when'
            nearest_idx = i0 if alpha < 0.5 else i1
            ctx = _row_from_time_index(ds, nearest_idx, lat_q, lon_q, True)
            # copy only neighborhood columns
            for k, v in ctx.items():
                if k.endswith(("_neigh_mean", "_neigh_min", "_neigh_max")):
                    rec[k] = v

        return pd.DataFrame([rec])

    raise ValueError("interp must be 'nearest' or 'linear'.")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Point stats from FourCastNet forecast outputs")
    p.add_argument("--lat", type=float, required=True, help="Latitude in degrees [-90, 90]")
    p.add_argument("--lon", type=float, required=True, help="Longitude in degrees (either -180..180 or 0..360)")
    p.add_argument("--no-context", action="store_true", help="Disable 3x3 neighborhood stats")
    p.add_argument("--csv", type=str, default="point_stats.csv", help="Output CSV filename")
    p.add_argument("--when", type=str, default=None,
                   help="ISO8601 time (e.g., 2023-01-01T09:00:00Z). If set, returns a single row at that time.")
    p.add_argument("--interp", type=str, default="nearest", choices=["nearest", "linear"],
                   help="Time interpolation mode when --when is provided.")
    args = p.parse_args()

    ds = _load_dataset()

    if args.when:
        df = point_at_time(args.lat, args.lon, args.when, interp=args.interp,
                           want_context=(not args.no_context), ds=ds)
        df.to_csv(args.csv, index=False)
        print(f"Wrote 1 row ({args.interp}) → {args.csv}")
    else:
        df = point_timeseries(args.lat, args.lon, want_context=(not args.no_context), ds=ds)
        df.to_csv(args.csv, index=False)
        print(f"Wrote {len(df)} rows and {len(df.columns)} columns → {args.csv}")
