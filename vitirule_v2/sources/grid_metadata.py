"""
Calculo de distancia horizontal (Haversine, km) e diferenca de altitude (m)
entre cada estacao de referencia e o ponto de grade servido por cada fonte
meteorologica. Nenhuma correcao de altitude entra na analise principal.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia geodesica em km sobre esfera media WGS-84."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def nearest_merra2_center(lat: float, lon: float) -> tuple[float, float]:
    """
    Centro da celula MERRA-2 (grade regular 0,5 grau lat x 0,625 grau lon) mais
    proximo de `(lat, lon)` usada pelo NASA POWER.
    """
    grid_lat = round(lat / 0.5) * 0.5
    grid_lon = round(lon / 0.625) * 0.625
    return round(grid_lat, 4), round(grid_lon, 4)


def nearest_era5_025_center(lat: float, lon: float) -> tuple[float, float]:
    """
    Centro da celula ERA5 (grade regular 0,25 grau lat x 0,25 grau lon) mais
    proximo de `(lat, lon)`, usado para precipitacao, vento e radiacao no
    modelo combinado `era5_seamless` do Open-Meteo Archive.
    """
    grid_lat = round(lat / 0.25) * 0.25
    grid_lon = round(lon / 0.25) * 0.25
    return round(grid_lat, 4), round(grid_lon, 4)


@dataclass(frozen=True)
class StationGridMatch:
    network: str
    station_id: str
    station_name: str
    source: str
    station_lat: float
    station_lon: float
    station_elev_m: float | None
    grid_lat: float
    grid_lon: float
    grid_elev_m: float | None
    distance_km: float
    elev_diff_m: float | None
    model_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_station_grid_match(
    network: str,
    station_id: str,
    station_name: str,
    source: str,
    station_lat: float,
    station_lon: float,
    station_elev_m: float | None,
    grid_lat: float,
    grid_lon: float,
    grid_elev_m: float | None,
    model_note: str = "",
) -> StationGridMatch:
    dist = round(haversine_km(station_lat, station_lon, grid_lat, grid_lon), 3)
    elev_diff = (
        round(grid_elev_m - station_elev_m, 2)
        if (grid_elev_m is not None and station_elev_m is not None)
        else None
    )
    return StationGridMatch(
        network=network,
        station_id=station_id,
        station_name=station_name,
        source=source,
        station_lat=round(station_lat, 5),
        station_lon=round(station_lon, 5),
        station_elev_m=round(station_elev_m, 2) if station_elev_m is not None else None,
        grid_lat=round(grid_lat, 5),
        grid_lon=round(grid_lon, 5),
        grid_elev_m=round(grid_elev_m, 2) if grid_elev_m is not None else None,
        distance_km=dist,
        elev_diff_m=elev_diff,
        model_note=model_note,
    )
