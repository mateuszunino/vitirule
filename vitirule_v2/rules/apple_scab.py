"""
Tabela de Mills revisada para sarna da macieira (*Venturia inaequalis*):
- MacHardy & Gadoury (1989), Phytopathology 79:304-310
- Stensvand et al. (1997), Phytopathology 87:1046-1053 (baixas temperaturas)
- Regra operacional de interrupcao seca <= 8 h (OMAFRA)

Implementacao pura em biblioteca padrao Python (compativel com Pyodide).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .common import HourlyRecord, load_params, local_day_for_timestamp, normalize_records
from .phenology import filter_records_by_phenology, season_label_for_date

_SEVERITY_RANK = {"light": 1, "moderate": 2, "heavy": 3}


@dataclass(frozen=True)
class MillsEvent:
    """Evento de infeccao primaria de sarna da macieira pela tabela revisada de Mills."""

    season_label: str
    onset_ts: datetime
    light_ts: datetime
    moderate_ts: datetime | None
    heavy_ts: datetime | None
    end_ts: datetime
    max_severity: str
    wet_hours: int
    mean_temp_c: float
    rain_mm: float


def mills_thresholds(temp_c: float | None) -> tuple[float, float, float] | None:
    """
    Retorna `(light_h, moderate_h, heavy_h)` interpolados linearmente da tabela
    publicada de MacHardy & Gadoury (1989) + Stensvand et al. (1997), ou `None`
    fora de `[1.0, 26.0] C`.
    """
    cfg = load_params()["mills_revised"]
    if temp_c is None or not math.isfinite(temp_c):
        return None
    if temp_c < float(cfg["temp_min_c"]) or temp_c > float(cfg["temp_max_c"]):
        return None

    rows = cfg["severity_table"]
    if temp_c <= float(rows[0]["temp_c"]):
        r = rows[0]
        return float(r["light_h"]), float(r["moderate_h"]), float(r["heavy_h"])
    if temp_c >= float(rows[-1]["temp_c"]):
        r = rows[-1]
        return float(r["light_h"]), float(r["moderate_h"]), float(r["heavy_h"])

    for i in range(len(rows) - 1):
        r0, r1 = rows[i], rows[i + 1]
        t0, t1 = float(r0["temp_c"]), float(r1["temp_c"])
        if t0 <= temp_c <= t1:
            if t1 == t0:
                return float(r0["light_h"]), float(r0["moderate_h"]), float(r0["heavy_h"])
            frac = (temp_c - t0) / (t1 - t0)
            light = float(r0["light_h"]) + frac * (float(r1["light_h"]) - float(r0["light_h"]))
            mod = float(r0["moderate_h"]) + frac * (float(r1["moderate_h"]) - float(r0["moderate_h"]))
            heavy = float(r0["heavy_h"]) + frac * (float(r1["heavy_h"]) - float(r0["heavy_h"]))
            return light, mod, heavy
    return None


def mills_lookup(temp_c: float | None, wet_hours: float) -> str | None:
    """Classifica `(temp_c, wet_hours)` em `'light'`, `'moderate'`, `'heavy'` ou `None`."""
    if not math.isfinite(wet_hours) or wet_hours <= 0.0:
        return None
    thresh = mills_thresholds(temp_c)
    if thresh is None:
        return None
    light_h, mod_h, heavy_h = thresh
    if wet_hours >= heavy_h:
        return "heavy"
    if wet_hours >= mod_h:
        return "moderate"
    if wet_hours >= light_h:
        return "light"
    return None


def detect_mills_infections(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    tz_name: str = "Europe/Paris",
    hemisphere: str = "northern_hemisphere",
    apply_phenology: bool = True,
) -> list[MillsEvent]:
    """
    Detecta eventos de infeccao primaria de sarna da macieira pela tabela
    revisada de Mills (MacHardy & Gadoury 1989; Stensvand et al. 1997).

    Regras congeladas em `params.json`:
    - Janela fenologica primaria da macieira quando `apply_phenology=True`.
    - Evento inicia em hora molhada com chuva na mesma hora ou na hora anterior,
      exigindo acumulado minimo de `0,2 mm` de chuva no evento.
    - Interrupcoes secas de ate `8 horas` consecutivas sao toleradas e combinam
      os blocos molhados, somando apenas horas molhadas na duracao e na media
      de temperatura. Interrupcoes acima de `8 horas` encerram o evento.
    """
    cfg = load_params()["mills_revised"]
    max_dry = int(cfg["max_dry_interruption_hours"])
    min_rain = float(cfg["min_event_rain_mm"])
    lookback = int(cfg["rain_initiation_lookback_hours"])

    norm = normalize_records(records)
    if apply_phenology:
        norm = filter_records_by_phenology(
            norm,
            crop="apple",
            tz_name=tz_name,
            hemisphere=hemisphere,
            day_start_hour=0,
        )
    if not norm:
        return []

    events: list[MillsEvent] = []

    # Estado do evento ativo
    active = False
    onset_ts: datetime | None = None
    end_ts: datetime | None = None
    light_ts: datetime | None = None
    moderate_ts: datetime | None = None
    heavy_ts: datetime | None = None
    max_sev: str | None = None
    wet_hours = 0
    wet_temps: list[float] = []
    rain_mm = 0.0
    dry_run = 0
    event_season: str = ""

    def _finalize() -> None:
        nonlocal active, onset_ts, end_ts, light_ts, moderate_ts, heavy_ts, max_sev
        nonlocal wet_hours, wet_temps, rain_mm, dry_run, event_season
        if active and light_ts is not None and onset_ts is not None and end_ts is not None and max_sev is not None:
            mean_t = sum(wet_temps) / len(wet_temps)
            events.append(
                MillsEvent(
                    season_label=event_season,
                    onset_ts=onset_ts,
                    light_ts=light_ts,
                    moderate_ts=moderate_ts,
                    heavy_ts=heavy_ts,
                    end_ts=end_ts,
                    max_severity=max_sev,
                    wet_hours=wet_hours,
                    mean_temp_c=round(mean_t, 3),
                    rain_mm=round(rain_mm, 3),
                )
            )
        active = False
        onset_ts = None
        end_ts = None
        light_ts = None
        moderate_ts = None
        heavy_ts = None
        max_sev = None
        wet_hours = 0
        wet_temps = []
        rain_mm = 0.0
        dry_run = 0
        event_season = ""

    prev_ts: datetime | None = None
    prev_precip: float = 0.0

    for rec in norm:
        rec_day = local_day_for_timestamp(rec.ts, tz_name=tz_name, day_start_hour=0)
        rec_season = (
            season_label_for_date(rec_day, crop="apple", hemisphere=hemisphere)
            if apply_phenology
            else str(rec_day.year)
        ) or str(rec_day.year)

        if active and prev_ts is not None:
            delta_h = (rec.ts - prev_ts).total_seconds() / 3600.0
            missing_h = max(0, int(round(delta_h)) - 1)
            if rec_season != event_season:
                _finalize()
            elif missing_h > 0:
                dry_run += missing_h
                if dry_run > max_dry:
                    _finalize()

        cur_precip = rec.precip_mm if (rec.precip_mm is not None and rec.precip_mm > 0.0) else 0.0
        is_wet = rec.wet is True

        if is_wet:
            if not active:
                prev_rain_ok = (
                    lookback >= 1
                    and prev_ts is not None
                    and abs((rec.ts - prev_ts).total_seconds() - 3600.0) <= 60.0
                    and prev_precip > 0.0
                )
                if cur_precip > 0.0 or prev_rain_ok or min_rain <= 0.0:
                    active = True
                    onset_ts = rec.ts
                    end_ts = rec.ts
                    event_season = rec_season
                    wet_hours = 1
                    wet_temps = [rec.temp_c] if rec.temp_c is not None else []
                    rain_mm = cur_precip + (prev_precip if (prev_rain_ok and cur_precip == 0.0) else 0.0)
                    dry_run = 0
            else:
                dry_run = 0
                wet_hours += 1
                if rec.temp_c is not None:
                    wet_temps.append(rec.temp_c)
                rain_mm += cur_precip
                end_ts = rec.ts

            if active and wet_temps and rain_mm >= min_rain:
                mean_t = sum(wet_temps) / len(wet_temps)
                sev = mills_lookup(mean_t, float(wet_hours))
                if sev is not None:
                    rank = _SEVERITY_RANK[sev]
                    if light_ts is None and rank >= 1:
                        light_ts = rec.ts
                    if moderate_ts is None and rank >= 2:
                        moderate_ts = rec.ts
                    if heavy_ts is None and rank >= 3:
                        heavy_ts = rec.ts
                    if max_sev is None or rank > _SEVERITY_RANK[max_sev]:
                        max_sev = sev
        else:
            if active:
                dry_run += 1
                if dry_run > max_dry:
                    _finalize()

        prev_ts = rec.ts
        prev_precip = cur_precip

    if active:
        _finalize()

    return events
