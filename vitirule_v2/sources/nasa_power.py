"""
Coletor com cache em disco para a API horaria do NASA POWER (base MERRA-2).

Detalhe critico verificado na API (`power.larc.nasa.gov/api/temporal/hourly/point`):
- O padrao da API sem o parametro `time-standard` e `LST` (Local Solar Time).
- Este coletor solicita EXPLICITAMENTE `time-standard=UTC` e valida
  `header.time_standard == "UTC"` ao ler a resposta, impedindo deslocamentos
  horarios em relacao as estacoes de referencia em UTC.
- Unidades da API: `T2M` (C), `RH2M` (%), `PRECTOTCORR` (mm/h), `WS2M` (m/s a 2 m),
  `ALLSKY_SFC_SW_DWN` (MJ/h -> convertido para W/m2 multiplicando por 1e6/3600).
- Valores sentinela de preenchimento (`-999.0` ou menor que `-900`) viram `None`.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..rules.common import HourlyRecord
from .grid_metadata import nearest_merra2_center

UTC = timezone.utc

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_POWER_PARAMS = "T2M,RH2M,T2MDEW,PRECTOTCORR,WS2M,ALLSKY_SFC_SW_DWN"
MJ_PER_HR_TO_WM2 = 1_000_000.0 / 3600.0


def _clean_nasa_value(val: Any, fill_value: float = -999.0) -> float | None:
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num) or num <= fill_value + 1.0 or num <= -900.0:
        return None
    return num


def parse_nasa_power_payload(
    payload: dict[str, Any],
    requested_lat: float,
    requested_lon: float,
) -> tuple[list[HourlyRecord], dict[str, Any]]:
    """
    Valida `time_standard == "UTC"` e converte o JSON do NASA POWER em
    `HourlyRecord` em UTC mais metadados da grade MERRA-2.
    """
    header = payload.get("header") or {}
    time_std = str(header.get("time_standard") or "").upper()
    if time_std != "UTC":
        raise ValueError(
            f"NASA POWER retornou time_standard={time_std!r}; era obrigatorio 'UTC'."
        )
    fill_val = float(header.get("fill_value", -999.0))

    props = (payload.get("properties") or {}).get("parameter") or {}
    t_map = props.get("T2M") or {}
    rh_map = props.get("RH2M") or {}
    p_map = props.get("PRECTOTCORR") or {}
    w_map = props.get("WS2M") or {}
    sw_map = props.get("ALLSKY_SFC_SW_DWN") or {}

    keys = sorted(t_map.keys())
    records: list[HourlyRecord] = []
    for k in keys:
        ts = datetime.strptime(k, "%Y%m%d%H").replace(tzinfo=UTC)
        sw_mj = _clean_nasa_value(sw_map.get(k), fill_val)
        rad_wm2 = round(sw_mj * MJ_PER_HR_TO_WM2, 3) if sw_mj is not None else None
        records.append(
            HourlyRecord(
                ts=ts,
                temp_c=_clean_nasa_value(t_map.get(k), fill_val),
                rh_pct=_clean_nasa_value(rh_map.get(k), fill_val),
                precip_mm=_clean_nasa_value(p_map.get(k), fill_val),
                wet=None,
                wind_ms=_clean_nasa_value(w_map.get(k), fill_val),
                rad_wm2=rad_wm2,
            )
        )

    coords = (payload.get("geometry") or {}).get("coordinates") or []
    grid_elev = float(coords[2]) if len(coords) >= 3 and coords[2] is not None else None
    grid_lat, grid_lon = nearest_merra2_center(requested_lat, requested_lon)
    meta = {
        "source": "nasa_power",
        "model": "MERRA-2_0.5x0.625",
        "time_standard": time_std,
        "grid_lat": grid_lat,
        "grid_lon": grid_lon,
        "grid_elev_m": grid_elev,
        "wind_height_m": 2.0,
        "attribution": "NASA POWER (MERRA-2, US Government public domain)",
    }
    return records, meta


def build_nasa_power_params(
    lat: float,
    lon: float,
    start_yyyymmdd: str,
    end_yyyymmdd: str,
) -> dict[str, Any]:
    """Monta parametros HTTP exigindo explicitamente `time-standard=UTC`."""
    return {
        "parameters": NASA_POWER_PARAMS,
        "community": "AG",
        "longitude": round(float(lon), 5),
        "latitude": round(float(lat), 5),
        "start": start_yyyymmdd.replace("-", ""),
        "end": end_yyyymmdd.replace("-", ""),
        "format": "JSON",
        "time-standard": "UTC",
    }


def fetch_nasa_power_hourly(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    cache_dir: str | Path | None = None,
    station_tag: str = "",
    session: requests.Session | None = None,
    force: bool = False,
    max_retries: int = 4,
) -> tuple[list[HourlyRecord], dict[str, Any]]:
    """Baixa (ou le do cache) serie horaria NASA POWER em UTC."""
    s_clean = start_date.replace("-", "")
    e_clean = end_date.replace("-", "")
    cache_path = (
        Path(cache_dir) / "nasa_power" / f"{station_tag}_{s_clean}_{e_clean}_utc.json"
        if cache_dir is not None
        else None
    )

    if cache_path is not None and cache_path.is_file() and not force:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return parse_nasa_power_payload(payload, requested_lat=lat, requested_lon=lon)

    params = build_nasa_power_params(lat, lon, s_clean, e_clean)
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "vitirule-v2-research/2.0")

    last_exc: Exception | None = None
    payload = None
    for attempt in range(max_retries):
        try:
            resp = sess.get(NASA_POWER_URL, params=params, timeout=(10.0, 60.0))
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            payload = resp.json()
            break
        except requests.RequestException as exc:
            last_exc = exc
            if attempt + 1 < max_retries:
                time.sleep(2.0 * (2 ** attempt))
    if payload is None:
        assert last_exc is not None
        raise last_exc

    recs, meta = parse_nasa_power_payload(payload, requested_lat=lat, requested_lon=lon)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return recs, meta
