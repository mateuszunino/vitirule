"""
TOM-CAST para pinta-preta do tomateiro (*Alternaria solani*):
- Matriz de DSV de Madden, Pennypacker & MacNab (1978)
- Protocolo operacional de Pitblado (1988, 1992) e Gillespie, Srivastava & Pitblado (1993)

Inclui os dois modos de memoria exigidos pelo roadmap da v2:
- `self_reset`: fonte candidata acumula e zera DSV segundo seus proprios alertas.
- `reference_reset`: acumulador zera nas datas de pulverizacao da referencia medida.

Implementacao pura em biblioteca padrao Python (compativel com Pyodide).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from .common import HourlyRecord, group_by_local_day, load_params, normalize_records, round_half_up
from .phenology import in_phenology_window, season_label_for_date


@dataclass(frozen=True)
class TomcastDay:
    """Resultado diario do TOM-CAST na janela local de 12h a 12h."""

    day: date
    season_label: str
    wet_hours: int
    wet_temp_mean_c: float | None
    wet_temp_rounded_c: int | None
    dsv: int


@dataclass(frozen=True)
class TomcastSprayEvent:
    """Alerta de pulverizacao TOM-CAST no modo autonomo (`self_reset`)."""

    season_label: str
    trigger_date: date
    cum_dsv: int
    spray_index: int


@dataclass(frozen=True)
class TomcastIntervalResult:
    """Resultado de um intervalo de pulverizacao no modo `reference_reset`."""

    season_label: str
    interval_index: int
    interval_start_date: date
    reference_spray_date: date | None
    candidate_trigger_date: date | None
    candidate_dsv_at_ref: int
    reached_by_ref_date: bool
    lead_days: int | None


def tomcast_dsv_lookup(wet_temp_c: float | None, wet_hours: int) -> int:
    """
    Consulta a matriz publicada de DSV (0 a 4) para `wet_temp_c` e `wet_hours`.
    Usa arredondamento aritmetico padrao half-up ao inteiro mais proximo.
    """
    if wet_hours <= 0 or wet_temp_c is None or not math.isfinite(wet_temp_c):
        return 0
    t_int = round_half_up(wet_temp_c)
    table = load_params()["tomcast"]["dsv_table"]
    for row in table:
        if int(row["temp_min_c"]) <= t_int <= int(row["temp_max_c"]):
            dsv = 0
            for level, key in ((1, "dsv_1_h"), (2, "dsv_2_h"), (3, "dsv_3_h"), (4, "dsv_4_h")):
                limit = row[key]
                if limit is not None and wet_hours >= int(limit):
                    dsv = level
            return dsv
    return 0


def compute_tomcast_daily(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    tz_name: str = "Europe/Paris",
    hemisphere: str = "northern_hemisphere",
    apply_phenology: bool = True,
) -> list[TomcastDay]:
    """
    Calcula o DSV diario do TOM-CAST em janelas locais de 12h a 12h.
    """
    cfg = load_params()["tomcast"]
    day_start_hour = int(cfg["day_start_hour_local"])

    norm = normalize_records(records)
    if not norm:
        return []

    grouped = group_by_local_day(norm, tz_name=tz_name, day_start_hour=day_start_hour)
    out: list[TomcastDay] = []
    for day, block in grouped:
        if apply_phenology and not in_phenology_window(day, crop="tomato", hemisphere=hemisphere):
            continue
        season_lbl = (
            season_label_for_date(day, crop="tomato", hemisphere=hemisphere)
            if apply_phenology
            else str(day.year)
        )
        assert season_lbl is not None

        wet_recs = [r for r in block if r.wet is True]
        wet_h = len(wet_recs)
        wet_temps = [r.temp_c for r in wet_recs if r.temp_c is not None]
        if wet_h > 0 and wet_temps:
            mean_t = sum(wet_temps) / len(wet_temps)
            t_round = round_half_up(mean_t)
            dsv = tomcast_dsv_lookup(mean_t, wet_h)
            out.append(
                TomcastDay(
                    day=day,
                    season_label=season_lbl,
                    wet_hours=wet_h,
                    wet_temp_mean_c=round(mean_t, 3),
                    wet_temp_rounded_c=t_round,
                    dsv=dsv,
                )
            )
        else:
            out.append(
                TomcastDay(
                    day=day,
                    season_label=season_lbl,
                    wet_hours=wet_h,
                    wet_temp_mean_c=None,
                    wet_temp_rounded_c=None,
                    dsv=0,
                )
            )
    return out


def simulate_tomcast_sprays(
    daily_days: Sequence[TomcastDay],
    threshold: int | None = None,
    mode: str = "self_reset",
    reference_spray_dates: Iterable[date] | None = None,
) -> list[TomcastSprayEvent] | list[TomcastIntervalResult]:
    """
    Simula alertas de pulverizacao TOM-CAST a partir da serie diaria de DSV.

    Modos suportados:
    - `'self_reset'`: acumula DSV da propria fonte e zera ao atingir `threshold`.
    - `'reference_reset'`: zera o acumulador nas datas de pulverizacao da
      referencia medida, avaliando cada intervalo sem propagar deriva entre
      pulverizacoes consecutivas.
    """
    thresh = int(load_params()["tomcast"]["spray_dsv_threshold"] if threshold is None else threshold)
    if thresh <= 0:
        raise ValueError(f"threshold deve ser positivo: {thresh}")
    if mode not in ("self_reset", "reference_reset"):
        raise ValueError(f"modo invalido: {mode!r}. Use 'self_reset' ou 'reference_reset'.")

    by_season: dict[str, list[TomcastDay]] = {}
    for item in sorted(daily_days, key=lambda d: d.day):
        by_season.setdefault(item.season_label, []).append(item)

    if mode == "self_reset":
        sprays: list[TomcastSprayEvent] = []
        for season_lbl, days in by_season.items():
            cum = 0
            idx = 0
            for item in days:
                cum += item.dsv
                if cum >= thresh:
                    idx += 1
                    sprays.append(
                        TomcastSprayEvent(
                            season_label=season_lbl,
                            trigger_date=item.day,
                            cum_dsv=cum,
                            spray_index=idx,
                        )
                    )
                    cum = 0
        return sprays

    if reference_spray_dates is None:
        raise ValueError("reference_spray_dates e obrigatorio no modo 'reference_reset'")
    ref_set = set(reference_spray_dates)

    intervals: list[TomcastIntervalResult] = []
    for season_lbl, days in by_season.items():
        if not days:
            continue
        cum = 0
        interval_idx = 0
        interval_start = days[0].day
        cand_trigger: date | None = None

        for i, item in enumerate(days):
            cum += item.dsv
            if cand_trigger is None and cum >= thresh:
                cand_trigger = item.day

            if item.day in ref_set:
                interval_idx += 1
                reached = cand_trigger is not None
                lead = (cand_trigger - item.day).days if cand_trigger is not None else None
                intervals.append(
                    TomcastIntervalResult(
                        season_label=season_lbl,
                        interval_index=interval_idx,
                        interval_start_date=interval_start,
                        reference_spray_date=item.day,
                        candidate_trigger_date=cand_trigger,
                        candidate_dsv_at_ref=cum,
                        reached_by_ref_date=reached,
                        lead_days=lead,
                    )
                )
                cum = 0
                cand_trigger = None
                if i + 1 < len(days):
                    interval_start = days[i + 1].day

        # Intervalo residual apos a ultima pulverizacao da referencia:
        # registra eventual alarme falso tardio da candidata
        if cand_trigger is not None:
            interval_idx += 1
            intervals.append(
                TomcastIntervalResult(
                    season_label=season_lbl,
                    interval_index=interval_idx,
                    interval_start_date=interval_start,
                    reference_spray_date=None,
                    candidate_trigger_date=cand_trigger,
                    candidate_dsv_at_ref=cum,
                    reached_by_ref_date=False,
                    lead_days=None,
                )
            )

    return intervals
