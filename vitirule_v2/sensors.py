"""
Leitores isolados dos arquivos de sensores locais (INRAE AgroClim e Politecnico
di Torino) para a v2. Usa os limiares de binarizacao congelados em `params.json`.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .rules.common import HourlyRecord, load_params

UTC = timezone.utc


@dataclass(frozen=True)
class StationMetadata:
    network: str
    station_id: str
    name: str
    path: Path
    lat: float
    lon: float
    tz_name: str
    hemisphere: str
    used_in_v1: bool


V1_INRAE_METADATA: tuple[dict[str, Any], ...] = (
    {
        "station_id": "33080002",
        "name": "Bordeaux-Couhins",
        "filename": "33080002_bordeaux_couhins.tab",
        "lat": 44.75260,
        "lon": -0.56077,
        "tz_name": "Europe/Paris",
    },
    {
        "station_id": "68066002",
        "name": "Alsace-Colmar",
        "filename": "68066002_alsace_colmar.tab",
        "lat": 48.06429,
        "lon": 7.33012,
        "tz_name": "Europe/Paris",
    },
    {
        "station_id": "51242002",
        "name": "Champagne-Fagnieres",
        "filename": "51242002_champagne_fagnieres.tab",
        "lat": 48.94978,
        "lon": 4.31402,
        "tz_name": "Europe/Paris",
    },
    {
        "station_id": "21106002",
        "name": "Bourgogne-Breteniere",
        "filename": "21106002_bourgogne_breteniere.tab",
        "lat": 47.23917,
        "lon": 5.10232,
        "tz_name": "Europe/Paris",
    },
)


def _parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def load_inrae_records(
    path: str | Path,
    year_min: int | None = None,
    year_max: int | None = None,
) -> list[HourlyRecord]:
    """
    Le arquivo `.tab` horario do INRAE AgroClim mantendo leituras faltantes como
    `None` para avaliacao fiel de cobertura no controle de qualidade.
    """
    wet_thresh = float(load_params()["sensor_binarization"]["inrae"]["wet_threshold_gte"])
    records: list[HourlyRecord] = []
    with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            d_str = (row.get("date_j") or "").strip()
            h_str = (row.get("heure") or "").strip()
            if len(d_str) < 10 or not h_str:
                continue
            yr = int(d_str[:4])
            if year_min is not None and yr < year_min - 1:
                continue
            if year_max is not None and yr > year_max + 1:
                continue
            base = datetime.strptime(d_str[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            hr = int(float(h_str))
            ts = base + timedelta(hours=hr)

            temp_c = _parse_float(row.get("t"))
            rh_pct = _parse_float(row.get("u"))
            precip_mm = _parse_float(row.get("rr"))
            wind_kmh = _parse_float(row.get("vt"))
            wind_ms = (wind_kmh / 3.6) if wind_kmh is not None else None
            rg_jcm2 = _parse_float(row.get("rg"))
            rad_wm2 = (rg_jcm2 * (10_000.0 / 3600.0)) if rg_jcm2 is not None else None

            h_val = _parse_float(row.get("h"))
            if h_val is None or not (0.0 <= h_val <= 1.0):
                wet = None
            else:
                wet = bool(h_val >= wet_thresh)

            records.append(
                HourlyRecord(
                    ts=ts,
                    temp_c=temp_c,
                    rh_pct=rh_pct,
                    precip_mm=precip_mm,
                    wet=wet,
                    wind_ms=wind_ms,
                    rad_wm2=rad_wm2,
                )
            )
    return records


def load_polito_records(path: str | Path) -> list[HourlyRecord]:
    """
    Le arquivo `.csv` horario do Politecnico di Torino / iXem Labs mantendo
    leituras faltantes ou negativas de sensor como `None`.
    """
    wet_thresh = float(load_params()["sensor_binarization"]["polito"]["wet_threshold_gte"])
    records: list[HourlyRecord] = []
    with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            t_str = (row.get("time") or "").strip()
            if not t_str:
                continue
            ts = datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            temp_c = _parse_float(row.get("temperature"))
            rh_pct = _parse_float(row.get("rh"))
            precip_mm = _parse_float(row.get("rain"))
            wind_ms = _parse_float(row.get("wind_speed"))
            leaf_top = _parse_float(row.get("leaf_top"))
            if leaf_top is None or leaf_top < 0.0:
                wet = None
            else:
                wet = bool(leaf_top >= wet_thresh)

            records.append(
                HourlyRecord(
                    ts=ts,
                    temp_c=temp_c,
                    rh_pct=rh_pct,
                    precip_mm=precip_mm,
                    wet=wet,
                    wind_ms=wind_ms,
                    rad_wm2=None,
                )
            )
    return records


def discover_local_dev_stations(data_root: str | Path = "data/lwd_sensors") -> list[StationMetadata]:
    """Lista as estacoes locais ja presentes (4 INRAE v1 + 7 Politecnico)."""
    root = Path(data_root)
    stations: list[StationMetadata] = []

    inrae_dir = root / "inrae"
    for info in V1_INRAE_METADATA:
        p = inrae_dir / info["filename"]
        if p.is_file():
            stations.append(
                StationMetadata(
                    network="inrae",
                    station_id=info["station_id"],
                    name=info["name"],
                    path=p,
                    lat=float(info["lat"]),
                    lon=float(info["lon"]),
                    tz_name=info["tz_name"],
                    hemisphere="northern_hemisphere",
                    used_in_v1=True,
                )
            )

    polito_dir = root / "polito"
    sites_json = polito_dir / "sites.json"
    if sites_json.is_file():
        meta = json.loads(sites_json.read_text(encoding="utf-8"))
        for site in sorted(meta.get("sites", []), key=lambda s: s["ref"]):
            ref = site["ref"]
            p = polito_dir / ref
            if p.is_file():
                sid = Path(ref).stem
                stations.append(
                    StationMetadata(
                        network="polito",
                        station_id=sid,
                        name=f"PoliTO-{sid}",
                        path=p,
                        lat=float(site["lat"]),
                        lon=float(site["lon"]),
                        tz_name="Europe/Rome",
                        hemisphere="northern_hemisphere",
                        used_in_v1=True,
                    )
                )

    return stations
