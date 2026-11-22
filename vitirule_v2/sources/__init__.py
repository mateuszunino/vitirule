"""
vitirule_v2.sources
===================
Coletores com cache em disco e metadados espaciais (distancia e diferenca de
altitude ate o ponto de grade) das fontes meteorologicas candidatas da v2.
"""
from __future__ import annotations

from .grid_metadata import (
    StationGridMatch,
    build_station_grid_match,
    haversine_km,
    nearest_era5_025_center,
    nearest_merra2_center,
)
from .nasa_power import NASA_POWER_URL, fetch_nasa_power_hourly, parse_nasa_power_payload
from .open_meteo import (
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_HIST_FORECAST_URL,
    OPEN_METEO_PREV_RUNS_URL,
    fetch_era5_025_grid_meta,
    fetch_era5_combined,
    fetch_era5_land,
    fetch_historical_forecast,
    fetch_previous_runs,
)

__all__ = [
    "StationGridMatch",
    "haversine_km",
    "nearest_era5_025_center",
    "nearest_merra2_center",
    "build_station_grid_match",
    "NASA_POWER_URL",
    "fetch_nasa_power_hourly",
    "parse_nasa_power_payload",
    "OPEN_METEO_ARCHIVE_URL",
    "OPEN_METEO_HIST_FORECAST_URL",
    "OPEN_METEO_PREV_RUNS_URL",
    "fetch_era5_025_grid_meta",
    "fetch_era5_combined",
    "fetch_era5_land",
    "fetch_historical_forecast",
    "fetch_previous_runs",
]
