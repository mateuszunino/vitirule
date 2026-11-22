"""
Coletores com cache local em disco para as tres APIs do Open-Meteo (CC BY 4.0):
- ERA5-Land (`archive-api.open-meteo.com/v1/archive`, `models=era5_land`)
- Historical Forecast (`historical-forecast-api.open-meteo.com/v1/forecast`)
- Previous Runs (`previous-runs-api.open-meteo.com/v1/forecast`, horizontes 1-3 d)

Atribuicao obrigatoria: Weather data by Open-Meteo.com (CC BY 4.0).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

from ..rules.common import HourlyRecord

UTC = timezone.utc

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
OPEN_METEO_PREV_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

BASE_HOURLY_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "shortwave_radiation",
)


def _get_json_with_retry(
    url: str,
    params: dict[str, Any],
    session: requests.Session | None = None,
    max_retries: int = 4,
    timeout: tuple[float, float] = (10.0, 45.0),
) -> dict[str, Any]:
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "vitirule-v2-research/2.0 (non-commercial)")
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = sess.get(url, params=params, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt + 1 < max_retries:
                time.sleep(2.0 * (2 ** attempt))
    assert last_exc is not None
    raise last_exc


def _opt_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_open_meteo_hourly_payload(
    payload: dict[str, Any],
    suffix: str = "",
) -> tuple[list[HourlyRecord], dict[str, Any]]:
    """Converte resposta JSON do Open-Meteo em `HourlyRecord` UTC e metadados de grade."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []

    def _col(base: str) -> list[Any]:
        key = f"{base}{suffix}"
        vals = hourly.get(key)
        return vals if vals is not None else [None] * len(times)

    t_col = _col("temperature_2m")
    rh_col = _col("relative_humidity_2m")
    p_col = _col("precipitation")
    w_col = _col("wind_speed_10m")
    r_col = _col("shortwave_radiation")

    records: list[HourlyRecord] = []
    for i, raw_t in enumerate(times):
        if isinstance(raw_t, (int, float)):
            ts = datetime.fromtimestamp(int(raw_t), tz=UTC)
        else:
            ts = datetime.fromisoformat(str(raw_t)).replace(tzinfo=UTC)
        records.append(
            HourlyRecord(
                ts=ts,
                temp_c=_opt_float(t_col[i]),
                rh_pct=_opt_float(rh_col[i]),
                precip_mm=_opt_float(p_col[i]),
                wet=None,
                wind_ms=_opt_float(w_col[i]),
                rad_wm2=_opt_float(r_col[i]),
            )
        )

    meta = {
        "grid_lat": _opt_float(payload.get("latitude")),
        "grid_lon": _opt_float(payload.get("longitude")),
        "grid_elev_m": _opt_float(payload.get("elevation")),
        "timezone": payload.get("timezone"),
        "wind_height_m": 10.0,
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0)",
    }
    return records, meta


def _cached_fetch(
    url: str,
    params: dict[str, Any],
    cache_path: Path | None,
    session: requests.Session | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if cache_path is not None and cache_path.is_file() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    payload = _get_json_with_retry(url, params=params, session=session)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def fetch_era5_land(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    cache_dir: str | Path | None = None,
    station_tag: str = "",
    session: requests.Session | None = None,
    force: bool = False,
) -> tuple[list[HourlyRecord], dict[str, Any]]:
    """Baixa (ou le do cache) serie horaria ERA5-Land em UTC."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(BASE_HOURLY_VARS),
        "models": "era5_land",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    cache_path = (
        Path(cache_dir) / "era5_land" / f"{station_tag}_{start_date}_{end_date}.json"
        if cache_dir is not None
        else None
    )
    payload = _cached_fetch(OPEN_METEO_ARCHIVE_URL, params, cache_path, session=session, force=force)
    recs, meta = parse_open_meteo_hourly_payload(payload)
    meta["source"] = "era5_land"
    meta["model"] = "era5_land"
    return recs, meta


def fetch_historical_forecast(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    model: str = "best_match",
    cache_dir: str | Path | None = None,
    station_tag: str = "",
    session: requests.Session | None = None,
    force: bool = False,
) -> tuple[list[HourlyRecord], dict[str, Any]]:
    """Baixa (ou le do cache) serie horaria do Open-Meteo Historical Forecast em UTC."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(BASE_HOURLY_VARS),
        "models": model,
        "timezone": "GMT",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    cache_path = (
        Path(cache_dir) / "historical_forecast" / f"{station_tag}_{model}_{start_date}_{end_date}.json"
        if cache_dir is not None
        else None
    )
    payload = _cached_fetch(OPEN_METEO_HIST_FORECAST_URL, params, cache_path, session=session, force=force)
    recs, meta = parse_open_meteo_hourly_payload(payload)
    meta["source"] = "historical_forecast"
    meta["model"] = model
    return recs, meta


def fetch_previous_runs(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    lead_days: Sequence[int] = (1, 2, 3),
    cache_dir: str | Path | None = None,
    station_tag: str = "",
    session: requests.Session | None = None,
    force: bool = False,
) -> tuple[dict[int, list[HourlyRecord]], dict[str, Any]]:
    """
    Baixa (ou le do cache) previsoes arquivadas com horizontes fixos de 1 a 3 dias
    (`previous_day1`, `previous_day2`, `previous_day3`) em UTC para a analise
    secundaria B (2024-2025).
    """
    hourly_fields = [
        f"{var}_previous_day{d}"
        for d in lead_days
        for var in BASE_HOURLY_VARS
    ]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(hourly_fields),
        "timezone": "GMT",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    leads_str = "-".join(str(d) for d in lead_days)
    cache_path = (
        Path(cache_dir) / "previous_runs" / f"{station_tag}_d{leads_str}_{start_date}_{end_date}.json"
        if cache_dir is not None
        else None
    )
    payload = _cached_fetch(OPEN_METEO_PREV_RUNS_URL, params, cache_path, session=session, force=force)

    by_lead: dict[int, list[HourlyRecord]] = {}
    meta: dict[str, Any] = {}
    for d in lead_days:
        recs, meta = parse_open_meteo_hourly_payload(payload, suffix=f"_previous_day{d}")
        by_lead[int(d)] = recs
    meta["source"] = "previous_runs"
    meta["lead_days"] = list(lead_days)
    return by_lead, meta
