"""
Regras classicas publicadas para o mildio da videira (*Plasmopara viticola*):
- Regra 3-10 de Baldacci (1947)
- Calendario de incubacao de Muller & Sleumer (1934) / Goidanich (1964)

Implementacao pura em biblioteca padrao Python (compativel com Pyodide).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from .common import HourlyRecord, group_by_local_day, load_params, normalize_records
from .phenology import in_phenology_window, season_label_for_date


@dataclass(frozen=True)
class Rule310Event:
    """Evento de infeccao primaria detectado pela regra 3-10."""

    trigger_date: date
    season_label: str
    temp_mean_c: float
    temp_min_c: float
    temp_aggregation: str
    rain_24h_mm: float
    rain_48h_mm: float
    is_first_of_season: bool


@dataclass(frozen=True)
class GoidanichCohort:
    """Coorte de incubacao de Goidanich iniciada por um evento primario."""

    trigger_date: date
    season_label: str
    completed: bool
    completion_date: date | None
    duration_days: int | None
    preventive_80_date: date | None
    final_cum_pct: float


def _daily_summary_map(
    records: Sequence[HourlyRecord],
    tz_name: str,
    day_start_hour: int,
) -> list[tuple[date, float | None, float | None, float | None, float]]:
    """Retorna lista ordenada de `(day, temp_mean_c, temp_min_c, rh_mean_pct, rain_24h_mm)`."""
    grouped = group_by_local_day(records, tz_name=tz_name, day_start_hour=day_start_hour)
    out: list[tuple[date, float | None, float | None, float | None, float]] = []
    for day, block in grouped:
        temps = [r.temp_c for r in block if r.temp_c is not None]
        rhs = [r.rh_pct for r in block if r.rh_pct is not None]
        rains = [r.precip_mm for r in block if r.precip_mm is not None and r.precip_mm >= 0.0]
        t_mean = (sum(temps) / len(temps)) if temps else None
        t_min = min(temps) if temps else None
        rh_mean = (sum(rhs) / len(rhs)) if rhs else None
        rain_24 = sum(rains) if rains else 0.0
        out.append((day, t_mean, t_min, rh_mean, rain_24))
    return out


def detect_rule_3_10(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    tz_name: str = "Europe/Paris",
    hemisphere: str = "northern_hemisphere",
    apply_phenology: bool = True,
    temp_aggregation: str | None = None,
) -> list[Rule310Event]:
    """
    Detecta eventos de infeccao primaria pela regra 3-10 (Baldacci 1947).

    Condicoes congeladas em `params.json` (com emenda pre-Fase 3):
    - Dia dentro da janela fenologica da videira (substituto fixo para broto >= 10 cm)
    - Temperatura diaria >= 10,0 C segundo `temp_aggregation`:
      * `'daily_min'` (padrao emendado, redacao classica italiana de Baldacci 1947,
        Goidanich 1964 e Rossi et al. 2008)
      * `'daily_mean'` (versao original de `v2-rules`, mantida para comparacao pareada)
    - Precipitacao acumulada em 48 h >= 10,0 mm (dia atual + dia imediatamente anterior)
    - Chuva ativa no dia do disparo >= 0,2 mm
    - Dias consecutivos que satisfazem o criterio sao agrupados no primeiro dia
    """
    cfg = load_params()["rule_3_10"]
    temp_min_c = float(cfg["temp_min_c"])
    agg_mode = str(cfg["temp_aggregation"] if temp_aggregation is None else temp_aggregation)
    if agg_mode not in ("daily_min", "daily_mean"):
        raise ValueError(f"temp_aggregation invalido: {agg_mode!r}. Use 'daily_min' ou 'daily_mean'.")

    rain_min_mm = float(cfg["rain_min_mm"])
    trigger_min_rain = float(cfg["trigger_day_min_rain_mm"])
    debounce = bool(cfg["debounce_consecutive_days"])
    day_start_hour = int(cfg["day_start_hour_local"])

    norm = normalize_records(records)
    if not norm:
        return []

    daily = _daily_summary_map(norm, tz_name=tz_name, day_start_hour=day_start_hour)
    events: list[Rule310Event] = []
    seen_seasons: set[str] = set()

    prev_day: date | None = None
    prev_rain_24: float = 0.0
    prev_triggered_day: date | None = None

    for day, t_mean, t_min, _rh_mean, rain_24 in daily:
        if prev_day is not None and (day - prev_day) == timedelta(days=1):
            rain_48 = rain_24 + prev_rain_24
        else:
            rain_48 = rain_24

        temp_val = t_min if agg_mode == "daily_min" else t_mean
        in_window = (not apply_phenology) or in_phenology_window(day, crop="grapevine", hemisphere=hemisphere)
        triggered = (
            in_window
            and temp_val is not None
            and t_mean is not None
            and t_min is not None
            and temp_val >= temp_min_c
            and rain_24 >= trigger_min_rain
            and rain_48 >= rain_min_mm
        )

        if triggered:
            is_continuation = (
                debounce
                and prev_triggered_day is not None
                and (day - prev_triggered_day) == timedelta(days=1)
            )
            if not is_continuation:
                season_lbl = (
                    season_label_for_date(day, crop="grapevine", hemisphere=hemisphere)
                    if apply_phenology
                    else str(day.year)
                )
                assert season_lbl is not None
                is_first = season_lbl not in seen_seasons
                seen_seasons.add(season_lbl)
                events.append(
                    Rule310Event(
                        trigger_date=day,
                        season_label=season_lbl,
                        temp_mean_c=round(t_mean, 3),
                        temp_min_c=round(t_min, 3),
                        temp_aggregation=agg_mode,
                        rain_24h_mm=round(rain_24, 3),
                        rain_48h_mm=round(rain_48, 3),
                        is_first_of_season=is_first,
                    )
                )
            prev_triggered_day = day

        prev_day = day
        prev_rain_24 = rain_24

    return events


def _interp_linear(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return float(ys[i])
            frac = (x - x0) / (x1 - x0)
            return float(ys[i] + frac * (ys[i + 1] - ys[i]))
    return float(ys[-1])


def goidanich_daily_progress_pct(
    temp_mean_c: float | None,
    rh_mean_pct: float | None = None,
) -> float:
    """
    Progresso diario em percentual da incubacao de *Plasmopara viticola*
    conforme tabela de Muller & Sleumer (1934) e ajuste de umidade de
    Goidanich (1964).
    """
    cfg = load_params()["goidanich"]
    tmin_c = float(cfg["tmin_c"])
    tmax_c = float(cfg["tmax_c"])
    if temp_mean_c is None or not math.isfinite(temp_mean_c):
        return 0.0
    if temp_mean_c <= tmin_c or temp_mean_c >= tmax_c:
        return 0.0

    xs = [float(v) for v in cfg["temp_anchor_c"]]
    ys = [float(v) for v in cfg["daily_pct_anchor"]]
    base_pct = _interp_linear(temp_mean_c, xs, ys)

    rh_thresh = float(cfg["rh_low_threshold_pct"])
    rh_factor = float(cfg["rh_low_factor"])
    if rh_mean_pct is not None and math.isfinite(rh_mean_pct) and rh_mean_pct < rh_thresh:
        base_pct *= rh_factor
    return round(base_pct, 4)


def track_goidanich_incubation(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    trigger_dates: Sequence[date] | None = None,
    tz_name: str = "Europe/Paris",
    hemisphere: str = "northern_hemisphere",
    apply_phenology: bool = True,
    temp_aggregation: str | None = None,
) -> list[GoidanichCohort]:
    """
    Rastreia coortes de incubacao de Goidanich ate 100%.

    Se `trigger_dates` for omitido, os gatilhos sao obtidos pela propria regra
    3-10 sobre `records` (modo acoplado). Passar `trigger_dates` explicitos
    permite modo diagnostico para isolar o vies de temperatura/UR na incubacao.
    """
    cfg = load_params()["goidanich"]
    completion_pct = float(cfg["completion_threshold_pct"])
    preventive_pct = float(cfg["preventive_advisory_pct"])
    start_offset = int(cfg["start_offset_days"])
    day_start_hour = int(cfg["day_start_hour_local"])

    norm = normalize_records(records)
    if not norm:
        return []

    if trigger_dates is None:
        triggers = [
            ev.trigger_date
            for ev in detect_rule_3_10(
                norm,
                tz_name=tz_name,
                hemisphere=hemisphere,
                apply_phenology=apply_phenology,
                temp_aggregation=temp_aggregation,
            )
        ]
    else:
        triggers = sorted(set(trigger_dates))

    if not triggers:
        return []

    daily_list = _daily_summary_map(norm, tz_name=tz_name, day_start_hour=day_start_hour)
    daily_by_date: dict[date, tuple[float | None, float | None]] = {
        d: (t_mean, rh_mean) for d, t_mean, _t_min, rh_mean, _rain in daily_list
    }
    sorted_dates = [d for d, _, _, _, _ in daily_list]

    cohorts: list[GoidanichCohort] = []
    for trig in triggers:
        season_lbl = (
            season_label_for_date(trig, crop="grapevine", hemisphere=hemisphere)
            if apply_phenology
            else str(trig.year)
        )
        if season_lbl is None:
            season_lbl = str(trig.year)

        start_day = trig + timedelta(days=start_offset)
        cum_pct = 0.0
        prev_80: date | None = None
        comp_date: date | None = None

        for d in sorted_dates:
            if d < start_day:
                continue
            if apply_phenology:
                d_season = season_label_for_date(d, crop="grapevine", hemisphere=hemisphere)
                if d_season != season_lbl:
                    break
            t_mean, rh_mean = daily_by_date[d]
            cum_pct += goidanich_daily_progress_pct(t_mean, rh_mean)
            if prev_80 is None and cum_pct >= preventive_pct:
                prev_80 = d
            if cum_pct >= completion_pct:
                comp_date = d
                break

        cohorts.append(
            GoidanichCohort(
                trigger_date=trig,
                season_label=season_lbl,
                completed=comp_date is not None,
                completion_date=comp_date,
                duration_days=(comp_date - trig).days if comp_date is not None else None,
                preventive_80_date=prev_80,
                final_cum_pct=round(cum_pct, 3),
            )
        )

    return cohorts
