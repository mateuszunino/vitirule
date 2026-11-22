"""
Coletores com cache local em disco para as tres APIs do Open-Meteo (CC BY 4.0):
- ERA5 combinado: T e UR do ERA5-Land (0,1 grau), chuva, vento e radiacao do
  ERA5 (0,25 grau) via `archive-api.open-meteo.com/v1/archive` (`models=era5_seamless`)
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
OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

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
    """
    Baixa (ou le do cache) serie horaria do ERA5 combinado via
    `models=era5_seamless` do Open-Meteo Archive em UTC.

    Segundo a documentacao do Open-Meteo, `era5_seamless` combina temperatura e
    umidade relativa do ERA5-Land (grade de 0,1 grau) com precipitacao, vento e
    radiacao do ERA5 (grade de 0,25 grau). As coordenadas e a altitude retornadas
    no cabecalho correspondem ao ponto de 0,1 grau do ERA5-Land; para o ponto de
    0,25 grau usado na precipitacao, consulte `fetch_era5_025_grid_meta`.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(BASE_HOURLY_VARS),
        "models": "era5_seamless",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    cache_path = (
        Path(cache_dir) / "era5_seamless" / f"{station_tag}_{start_date}_{end_date}.json"
        if cache_dir is not None
        else None
    )
    payload = _cached_fetch(OPEN_METEO_ARCHIVE_URL, params, cache_path, session=session, force=force)
    recs, meta = parse_open_meteo_hourly_payload(payload)
    if recs and all(r.precip_mm is None for r in recs):
        raise ValueError("Open-Meteo Archive retornou precipitation inteiramente nula")
    meta["source"] = "era5_combined"
    meta["source_label"] = "ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5"
    meta["model"] = "era5_seamless"
    return recs, meta


fetch_era5_combined = fetch_era5_land


def fetch_era5_025_grid_meta(
    lat: float,
    lon: float,
    sample_date: str = "2022-05-01",
    cache_dir: str | Path | None = None,
    station_tag: str = "",
    session: requests.Session | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Consulta um unico dia em `models=era5` no Open-Meteo Archive para obter
    exatamente as coordenadas do ponto de grade ERA5 de 0,25 grau usado para
    precipitacao, vento e radiacao no `era5_seamless`, e consulta a altitude
    desse ponto de grade via `/v1/elevation` (pois o campo `elevation` do
    cabecalho Archive devolve o DEM na coordenada da estacao, nao no centro
    da celula de 0,25 grau).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": sample_date,
        "end_date": sample_date,
        "hourly": "precipitation",
        "models": "era5",
        "timezone": "GMT",
        "timeformat": "unixtime",
    }
    cache_path = (
        Path(cache_dir) / "era5_025_meta" / f"{station_tag}_{sample_date}.json"
        if cache_dir is not None
        else None
    )
    payload = _cached_fetch(OPEN_METEO_ARCHIVE_URL, params, cache_path, session=session, force=force)
    glat = _opt_float(payload.get("latitude"))
    glon = _opt_float(payload.get("longitude"))
    grid_elev = _opt_float(payload.get("elevation"))

    if glat is not None and glon is not None:
        elev_cache = (
            Path(cache_dir) / "era5_025_meta" / f"{station_tag}_elev.json"
            if cache_dir is not None
            else None
        )
        try:
            elev_payload = _cached_fetch(
                OPEN_METEO_ELEVATION_URL,
                {"latitude": glat, "longitude": glon},
                elev_cache,
                session=session,
                force=force,
            )
            elev_list = elev_payload.get("elevation")
            if isinstance(elev_list, list) and elev_list:
                parsed = _opt_float(elev_list[0])
                if parsed is not None:
                    grid_elev = parsed
        except Exception:
            pass

    return {
        "source": "era5_combined_precip_025",
        "source_label": "ERA5 combinado (grade ERA5 0,25 grau para chuva, vento e radiação)",
        "model": "era5",
        "grid_lat": glat,
        "grid_lon": glon,
        "grid_elev_m": grid_elev,
        "api_dem_elev_m": _opt_float(payload.get("elevation")),
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0)",
    }


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
