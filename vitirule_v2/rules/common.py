"""
Utilitarios puros compartilhados pelas regras da v2.
Usa exclusivamente a biblioteca padrao Python (compativel com Pyodide).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

UTC = timezone.utc
PARAMS_PATH = Path(__file__).resolve().parent / "params.json"


@lru_cache(maxsize=1)
def load_params() -> dict[str, Any]:
    """Carrega e retorna uma copia dos parametros congelados em `params.json`."""
    with PARAMS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def round_half_up(value: float) -> int:
    """Arredondamento aritmetico padrao ao inteiro mais proximo (half-up)."""
    if not math.isfinite(value):
        raise ValueError(f"valor nao finito para arredondamento: {value!r}")
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def parse_aware_datetime(ts: str | datetime) -> datetime:
    """Converte string ISO 8601 ou datetime para datetime com fuso horario explicito."""
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        text = ts.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise TypeError(f"tipo invalido para timestamp: {type(ts).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timestamp sem fuso horario explicito: {ts!r}")
    return dt


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return None
        return bool(value > 0.5)
    raise ValueError(f"valor invalido para wet: {value!r}")


@dataclass(frozen=True)
class HourlyRecord:
    """Registro meteorologico horario padronizado para entrada nas regras puras."""

    ts: datetime
    temp_c: float | None
    rh_pct: float | None = None
    precip_mm: float | None = None
    wet: bool | None = None
    wind_ms: float | None = None
    rad_wm2: float | None = None


def normalize_records(records: Sequence[HourlyRecord | Mapping[str, Any]]) -> list[HourlyRecord]:
    """
    Normaliza sequencia de `HourlyRecord` ou dicionarios para lista ordenada
    cronologicamente em UTC. Rejeita timestamps sem fuso ou duplicados.
    """
    out: list[HourlyRecord] = []
    for rec in records:
        if isinstance(rec, HourlyRecord):
            ts_utc = parse_aware_datetime(rec.ts).astimezone(UTC)
            out.append(
                HourlyRecord(
                    ts=ts_utc,
                    temp_c=_opt_float(rec.temp_c),
                    rh_pct=_opt_float(rec.rh_pct),
                    precip_mm=_opt_float(rec.precip_mm),
                    wet=_opt_bool(rec.wet),
                    wind_ms=_opt_float(rec.wind_ms),
                    rad_wm2=_opt_float(rec.rad_wm2),
                )
            )
        elif isinstance(rec, Mapping):
            ts_utc = parse_aware_datetime(rec["ts"]).astimezone(UTC)
            out.append(
                HourlyRecord(
                    ts=ts_utc,
                    temp_c=_opt_float(rec.get("temp_c")),
                    rh_pct=_opt_float(rec.get("rh_pct")),
                    precip_mm=_opt_float(rec.get("precip_mm")),
                    wet=_opt_bool(rec.get("wet")),
                    wind_ms=_opt_float(rec.get("wind_ms")),
                    rad_wm2=_opt_float(rec.get("rad_wm2")),
                )
            )
        else:
            raise TypeError(f"registro horario invalido: {type(rec).__name__}")

    out.sort(key=lambda r: r.ts)
    for i in range(1, len(out)):
        if out[i].ts == out[i - 1].ts:
            raise ValueError(f"timestamp duplicado na serie horaria: {out[i].ts.isoformat()}")
    return out


def local_day_for_timestamp(ts_utc: datetime, tz_name: str, day_start_hour: int = 0) -> date:
    """
    Retorna a data local associada a `ts_utc` para janelas diarias que comecam
    em `day_start_hour` no fuso `tz_name` (0 para dia civil; 12 para 12h-12h).
    """
    tz = ZoneInfo(tz_name)
    local_dt = ts_utc.astimezone(tz) - timedelta(hours=day_start_hour)
    return local_dt.date()


def group_by_local_day(
    records: Sequence[HourlyRecord],
    tz_name: str,
    day_start_hour: int = 0,
) -> list[tuple[date, list[HourlyRecord]]]:
    """Agrupa registros horarios ja ordenados em blocos diarios locais ordenados."""
    buckets: dict[date, list[HourlyRecord]] = {}
    for rec in records:
        d = local_day_for_timestamp(rec.ts, tz_name, day_start_hour=day_start_hour)
        buckets.setdefault(d, []).append(rec)
    return sorted(buckets.items(), key=lambda kv: kv[0])
