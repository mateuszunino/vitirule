"""
Janelas fenologicas fixas por hemisferio e cultura, carregadas de `params.json`.
Aplicadas de forma identica a referencia medida e as fontes candidatas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from .common import HourlyRecord, load_params, local_day_for_timestamp


@dataclass(frozen=True)
class PhenologyWindow:
    crop: str
    hemisphere: str
    start_month: int
    start_day: int
    end_month: int
    end_day: int
    cross_year: bool
    reference: str


def get_phenology_window(crop: str, hemisphere: str = "northern_hemisphere") -> PhenologyWindow:
    """Retorna a janela fenologica congelada para `crop` e `hemisphere`."""
    params = load_params()["phenology_windows"]
    if hemisphere not in params or hemisphere == "notes":
        raise ValueError(f"hemisferio invalido: {hemisphere!r}")
    hemi_cfg = params[hemisphere]
    if crop not in hemi_cfg:
        raise ValueError(f"cultura invalida: {crop!r}. Use {sorted(hemi_cfg)}")
    cfg = hemi_cfg[crop]
    return PhenologyWindow(
        crop=crop,
        hemisphere=hemisphere,
        start_month=int(cfg["start_month"]),
        start_day=int(cfg["start_day"]),
        end_month=int(cfg["end_month"]),
        end_day=int(cfg["end_day"]),
        cross_year=bool(cfg["cross_year"]),
        reference=str(cfg["reference"]),
    )


def in_phenology_window(
    day: date,
    crop: str,
    hemisphere: str = "northern_hemisphere",
) -> bool:
    """Verifica se `day` cai dentro da janela fenologica fixa (inclusive)."""
    win = get_phenology_window(crop, hemisphere)
    md = (day.month, day.day)
    start_md = (win.start_month, win.start_day)
    end_md = (win.end_month, win.end_day)
    if not win.cross_year:
        return start_md <= md <= end_md
    return md >= start_md or md <= end_md


def season_label_for_date(
    day: date,
    crop: str,
    hemisphere: str = "northern_hemisphere",
) -> str | None:
    """
    Retorna o rotulo da safra (`'2022'` no Hemisferio Norte ou `'2022-2023'`
    para janelas que cruzam a virada do ano no Hemisferio Sul), ou `None` se
    `day` estiver fora da janela fenologica.
    """
    if not in_phenology_window(day, crop, hemisphere):
        return None
    win = get_phenology_window(crop, hemisphere)
    if not win.cross_year:
        return str(day.year)
    if (day.month, day.day) >= (win.start_month, win.start_day):
        return f"{day.year}-{day.year + 1}"
    return f"{day.year - 1}-{day.year}"


def season_date_bounds(
    season_year: int,
    crop: str,
    hemisphere: str = "northern_hemisphere",
) -> tuple[date, date]:
    """Retorna `(data_inicio, data_fim)` da safra iniciada em `season_year`."""
    win = get_phenology_window(crop, hemisphere)
    start_d = date(season_year, win.start_month, win.start_day)
    end_year = season_year + 1 if win.cross_year else season_year
    end_d = date(end_year, win.end_month, win.end_day)
    return start_d, end_d


def filter_records_by_phenology(
    records: Sequence[HourlyRecord],
    crop: str,
    tz_name: str,
    hemisphere: str = "northern_hemisphere",
    day_start_hour: int = 0,
) -> list[HourlyRecord]:
    """Filtra registros horarios mantendo apenas os dias dentro da janela fenologica."""
    return [
        rec
        for rec in records
        if in_phenology_window(
            local_day_for_timestamp(rec.ts, tz_name, day_start_hour=day_start_hour),
            crop=crop,
            hemisphere=hemisphere,
        )
    ]
