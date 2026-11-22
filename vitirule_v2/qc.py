"""
Controle de qualidade cego de estacoes-safra, mascaramento de lacunas com
periodo de aquecimento por regra e sorteio deterministico do lockbox.

Implementa `docs/v2/criterios_qualidade.md` e a Emenda 1 de `docs/v2/preregistro.md`:
- `gap_policy="mask_with_warmup"` (padrao emendado pre-Fase 2): mantem cobertura
  minima de 95% e todos os testes de deriva do sensor, substituindo a reprovacao
  por lacuna continua > 24 h pelo mascaramento da lacuna mais o periodo de
  aquecimento igual a memoria maxima de cada regra.
- `gap_policy="reject_24h"` (regra original congelada na Fase 0): mantida como
  analise de sensibilidade declarada no preregistro.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .rules.common import HourlyRecord, load_params, local_day_for_timestamp, parse_aware_datetime, round_half_up
from .rules.phenology import season_date_bounds

UTC = timezone.utc

# Limiares congelados de `docs/v2/criterios_qualidade.md`
MIN_COVERAGE = 0.95
MAX_GAP_HOURS = 24
TEMP_MIN_C = -20.0
TEMP_MAX_C = 50.0
RH_MIN_PCT = 5.0
RH_MAX_PCT = 100.0
RH_SATURATION_CAP_PCT = 105.0
PRECIP_MIN_MM = 0.0
PRECIP_MAX_MM = 150.0
MIN_WET_FRACTION = 0.01
MAX_WET_FRACTION = 0.80
DRY_MIDDAY_RH_LT = 60.0
DRY_MIDDAY_HOUR_START = 11
DRY_MIDDAY_HOUR_END = 16
MAX_DRY_MIDDAY_WET_FRACTION = 0.15
MAX_RAINLESS_WET_STREAK_H = 96
RAINLESS_LOOKBACK_H = 72
RAINLESS_MIN_RAIN_MM = 0.2

# Estacoes ja usadas na v1: obrigatoriamente fora do lockbox
V1_INRAE_STATION_IDS = frozenset({"33080002", "68066002", "51242002", "21106002"})


def rule_warmup_hours() -> dict[str, int]:
    """
    Deriva o periodo de aquecimento pos-lacuna em horas a partir dos parametros
    congelados em `vitirule_v2/rules/params.json`:
    - `rule_3_10`: `rain_window_hours` = 48 h (memoria da soma de chuva em 48 h).
    - `goidanich`: teto teorico da incubacao ate 100% a taxa minima positiva
      (10 C com UR < 75%: 5,0 * 0,85 = 4,25 %/dia -> ceil(100/4,25) = 24 dias = 576 h),
      alem da filtragem exata de qualquer coorte cuja janela toque hora mascarada.
    - `mills_revised`: `max_dry_interruption_hours` (8 h) + `rain_initiation_lookback_hours` (1 h) = 9 h.
    - `tomcast`: `spray_dsv_threshold` (15 DSV) a taxa minima positiva de 1 DSV/dia = 15 dias = 360 h,
      alem da filtragem exata de qualquer intervalo de pulverizacao que toque dia mascarado.
    """
    params = load_params()
    r310_h = int(params["rule_3_10"]["rain_window_hours"])

    g_cfg = params["goidanich"]
    min_pos_pct = min(v for v in g_cfg["daily_pct_anchor"] if v > 0.0) * float(g_cfg["rh_low_factor"])
    goid_days = int(math.ceil(float(g_cfg["completion_threshold_pct"]) / min_pos_pct))
    goid_h = goid_days * 24

    m_cfg = params["mills_revised"]
    mills_h = int(m_cfg["max_dry_interruption_hours"]) + int(m_cfg["rain_initiation_lookback_hours"])

    tc_days = int(params["tomcast"]["spray_dsv_threshold"])
    tc_h = tc_days * 24

    return {
        "rule_3_10": r310_h,
        "goidanich": goid_h,
        "mills_revised": mills_h,
        "tomcast": tc_h,
    }


@dataclass(frozen=True)
class StationSeasonQCResult:
    """Diagnostico completo de controle de qualidade para uma estacao-safra."""

    network: str
    station_id: str
    crop: str
    season_label: str
    gap_policy: str
    passed: bool
    reasons: tuple[str, ...]
    expected_hours: int
    valid_hours: int
    coverage_frac: float
    max_gap_hours: int
    n_gap_hours: int
    wet_fraction: float | None
    dry_midday_hours: int
    dry_midday_wet_fraction: float | None
    max_rainless_wet_streak_h: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d


def _is_valid_hour(rec: HourlyRecord, allow_rh_saturation_105: bool = True) -> bool:
    if rec.temp_c is None or not math.isfinite(rec.temp_c):
        return False
    if not (TEMP_MIN_C <= rec.temp_c <= TEMP_MAX_C):
        return False
    if rec.rh_pct is None or not math.isfinite(rec.rh_pct):
        return False
    rh_upper = RH_SATURATION_CAP_PCT if allow_rh_saturation_105 else RH_MAX_PCT
    if not (RH_MIN_PCT <= rec.rh_pct <= rh_upper):
        return False
    if rec.precip_mm is None or not math.isfinite(rec.precip_mm):
        return False
    if not (PRECIP_MIN_MM <= rec.precip_mm <= PRECIP_MAX_MM):
        return False
    if rec.wet is None:
        return False
    return True


def _extract_expected_grid_and_valid_map(
    raw_records: Sequence[HourlyRecord | Mapping[str, Any]],
    crop: str,
    season_year: int,
    tz_name: str,
    hemisphere: str,
    allow_rh_saturation_105: bool,
) -> tuple[str, list[datetime], dict[datetime, HourlyRecord], bool, bool, bool]:
    start_d, end_d = season_date_bounds(season_year, crop=crop, hemisphere=hemisphere)
    season_lbl = f"{season_year}-{season_year + 1}" if end_d.year > start_d.year else str(season_year)
    tz = ZoneInfo(tz_name)

    start_local = datetime(start_d.year, start_d.month, start_d.day, 0, 0, tzinfo=tz)
    end_local_excl = datetime(end_d.year, end_d.month, end_d.day, 0, 0, tzinfo=tz) + timedelta(days=1)
    start_utc = start_local.astimezone(UTC)
    end_utc_excl = end_local_excl.astimezone(UTC)

    expected_grid: list[datetime] = []
    cur = start_utc
    while cur < end_utc_excl:
        expected_grid.append(cur)
        cur += timedelta(hours=1)

    parsed_by_ts: dict[datetime, HourlyRecord] = {}
    prev_ts: datetime | None = None
    non_monotonic = False
    duplicate_ts = False
    naive_ts = False

    for raw in raw_records:
        try:
            raw_ts = raw.ts if isinstance(raw, HourlyRecord) else raw["ts"]
            ts_utc = parse_aware_datetime(raw_ts).astimezone(UTC)
        except ValueError:
            naive_ts = True
            continue
        if prev_ts is not None:
            if ts_utc < prev_ts:
                non_monotonic = True
            elif ts_utc == prev_ts:
                duplicate_ts = True
        prev_ts = ts_utc

        if not (start_utc <= ts_utc < end_utc_excl):
            continue

        if isinstance(raw, HourlyRecord):
            rh_adj = (
                min(raw.rh_pct, RH_MAX_PCT)
                if (raw.rh_pct is not None and raw.rh_pct <= RH_SATURATION_CAP_PCT and allow_rh_saturation_105)
                else raw.rh_pct
            )
            rec = HourlyRecord(
                ts=ts_utc,
                temp_c=raw.temp_c,
                rh_pct=rh_adj,
                precip_mm=raw.precip_mm,
                wet=raw.wet,
                wind_ms=raw.wind_ms,
                rad_wm2=raw.rad_wm2,
            )
        else:
            rh_raw = raw.get("rh_pct")
            rh_val = float(rh_raw) if (rh_raw is not None and math.isfinite(float(rh_raw))) else None
            if rh_val is not None and allow_rh_saturation_105 and RH_MAX_PCT < rh_val <= RH_SATURATION_CAP_PCT:
                rh_val = RH_MAX_PCT
            t_raw = raw.get("temp_c")
            t_val = float(t_raw) if (t_raw is not None and math.isfinite(float(t_raw))) else None
            p_raw = raw.get("precip_mm")
            p_val = float(p_raw) if (p_raw is not None and math.isfinite(float(p_raw))) else None
            w_raw = raw.get("wet")
            if w_raw is None:
                w_val = None
            elif isinstance(w_raw, bool):
                w_val = w_raw
            else:
                wf = float(w_raw)
                w_val = None if math.isnan(wf) else bool(wf > 0.5)
            rec = HourlyRecord(ts=ts_utc, temp_c=t_val, rh_pct=rh_val, precip_mm=p_val, wet=w_val)

        if ts_utc in parsed_by_ts:
            duplicate_ts = True
        parsed_by_ts[ts_utc] = rec

    return season_lbl, expected_grid, parsed_by_ts, naive_ts, non_monotonic, duplicate_ts


def compute_raw_gap_hours(
    raw_records: Sequence[HourlyRecord | Mapping[str, Any]],
    crop: str,
    season_year: int,
    tz_name: str,
    hemisphere: str = "northern_hemisphere",
    allow_rh_saturation_105: bool = True,
) -> set[datetime]:
    """Retorna apenas os timestamps UTC ausentes ou fisicamente invalidos na grade esperada."""
    _lbl, expected_grid, parsed_by_ts, _, _, _ = _extract_expected_grid_and_valid_map(
        raw_records, crop, season_year, tz_name, hemisphere, allow_rh_saturation_105
    )
    gaps: set[datetime] = set()
    for ts in expected_grid:
        rec = parsed_by_ts.get(ts)
        if rec is None or not _is_valid_hour(rec, allow_rh_saturation_105=allow_rh_saturation_105):
            gaps.add(ts)
    return gaps


def compute_masked_hours_for_rule(
    raw_records: Sequence[HourlyRecord | Mapping[str, Any]],
    rule_name: str,
    crop: str,
    season_year: int,
    tz_name: str,
    hemisphere: str = "northern_hemisphere",
    allow_rh_saturation_105: bool = True,
) -> set[datetime]:
    """
    Retorna o conjunto de timestamps UTC mascarados para `rule_name`:
    todas as horas invalidas/ausentes na grade esperada mais o periodo de
    aquecimento pos-lacuna igual a memoria maxima da regra (`rule_warmup_hours()`).
    """
    warmups = rule_warmup_hours()
    if rule_name not in warmups:
        raise ValueError(f"regra invalida: {rule_name!r}. Use {sorted(warmups)}")
    warmup_h = warmups[rule_name]

    _lbl, expected_grid, parsed_by_ts, _, _, _ = _extract_expected_grid_and_valid_map(
        raw_records, crop, season_year, tz_name, hemisphere, allow_rh_saturation_105
    )

    masked: set[datetime] = set()
    cooldown = 0
    for ts in expected_grid:
        rec = parsed_by_ts.get(ts)
        is_ok = rec is not None and _is_valid_hour(rec, allow_rh_saturation_105=allow_rh_saturation_105)
        if not is_ok:
            masked.add(ts)
            cooldown = warmup_h
        elif cooldown > 0:
            masked.add(ts)
            cooldown -= 1
    return masked


def masked_local_days(
    masked_hours_utc: Iterable[datetime],
    tz_name: str,
    day_start_hour: int = 0,
) -> set[date]:
    """Converte um conjunto de horas UTC mascaradas nos dias locais afetados."""
    return {
        local_day_for_timestamp(ts, tz_name=tz_name, day_start_hour=day_start_hour)
        for ts in masked_hours_utc
    }


def event_touches_masked_hours(
    window_start_utc: datetime,
    window_end_utc: datetime,
    masked_hours_utc: set[datetime],
) -> bool:
    """Retorna True se qualquer hora em `[window_start_utc, window_end_utc]` estiver mascarada."""
    if not masked_hours_utc:
        return False
    cur = window_start_utc.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    end = window_end_utc.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    while cur <= end:
        if cur in masked_hours_utc:
            return True
        cur += timedelta(hours=1)
    return False


def evaluate_station_season_qc(
    raw_records: Sequence[HourlyRecord | Mapping[str, Any]],
    network: str,
    station_id: str,
    crop: str,
    season_year: int,
    tz_name: str,
    hemisphere: str = "northern_hemisphere",
    allow_rh_saturation_105: bool = True,
    gap_policy: str = "mask_with_warmup",
) -> StationSeasonQCResult:
    """
    Avalia uma estacao-safra contra todos os criterios de controle de qualidade.

    `gap_policy`:
    - `'mask_with_warmup'` (padrao emendado): mantem >= 95% de cobertura e todos
      os testes de deriva; lacunas > 24 h nao reprovam a safra, sendo tratadas
      por mascaramento da lacuna e do periodo de aquecimento de cada regra.
    - `'reject_24h'` (regra original de `criterios_qualidade.md`, analise de
      sensibilidade): reprova qualquer safra com lacuna continua > 24 h.
    """
    if gap_policy not in ("mask_with_warmup", "reject_24h"):
        raise ValueError(f"gap_policy invalida: {gap_policy!r}. Use 'mask_with_warmup' ou 'reject_24h'.")

    tz = ZoneInfo(tz_name)
    season_lbl, expected_grid, parsed_by_ts, naive_ts, non_monotonic, duplicate_ts = (
        _extract_expected_grid_and_valid_map(
            raw_records, crop, season_year, tz_name, hemisphere, allow_rh_saturation_105
        )
    )
    expected_hours = len(expected_grid)
    reasons: list[str] = []

    if naive_ts:
        reasons.append("naive_timestamp")
    if non_monotonic:
        reasons.append("non_monotonic_timestamp")
    if duplicate_ts:
        reasons.append("duplicate_timestamp")

    valid_hours = 0
    max_gap = 0
    cur_gap = 0
    wet_hours = 0
    dry_midday_total = 0
    dry_midday_wet = 0

    rain_history: list[float] = []
    wet_streak = 0
    max_rainless_streak = 0

    for ts in expected_grid:
        rec = parsed_by_ts.get(ts)
        if rec is not None and _is_valid_hour(rec, allow_rh_saturation_105=allow_rh_saturation_105):
            valid_hours += 1
            cur_gap = 0
            rain_val = float(rec.precip_mm or 0.0)
            rain_history.append(rain_val)

            if rec.wet:
                wet_hours += 1
                wet_streak += 1
                last_72_rain = sum(rain_history[-RAINLESS_LOOKBACK_H:])
                if last_72_rain < RAINLESS_MIN_RAIN_MM and wet_streak > max_rainless_streak:
                    max_rainless_streak = wet_streak
            else:
                wet_streak = 0

            local_h = ts.astimezone(tz).hour
            if (
                rain_val == 0.0
                and rec.rh_pct is not None
                and rec.rh_pct < DRY_MIDDAY_RH_LT
                and DRY_MIDDAY_HOUR_START <= local_h <= DRY_MIDDAY_HOUR_END
            ):
                dry_midday_total += 1
                if rec.wet:
                    dry_midday_wet += 1
        else:
            cur_gap += 1
            if cur_gap > max_gap:
                max_gap = cur_gap
            rain_history.append(0.0)
            wet_streak = 0

    n_gap_hours = expected_hours - valid_hours
    coverage = valid_hours / expected_hours if expected_hours > 0 else 0.0
    if coverage < MIN_COVERAGE:
        reasons.append(f"coverage_below_{MIN_COVERAGE:.2f}")
    if gap_policy == "reject_24h" and max_gap > MAX_GAP_HOURS:
        reasons.append(f"max_gap_gt_{MAX_GAP_HOURS}h")

    wet_frac = (wet_hours / valid_hours) if valid_hours > 0 else None
    if wet_frac is None or wet_frac < MIN_WET_FRACTION:
        reasons.append(f"wet_fraction_below_{MIN_WET_FRACTION:.2f}")
    elif wet_frac > MAX_WET_FRACTION:
        reasons.append(f"wet_fraction_above_{MAX_WET_FRACTION:.2f}")

    dry_midday_wet_frac = (dry_midday_wet / dry_midday_total) if dry_midday_total > 0 else None
    if dry_midday_wet_frac is not None and dry_midday_wet_frac > MAX_DRY_MIDDAY_WET_FRACTION:
        reasons.append(f"dry_midday_wet_above_{MAX_DRY_MIDDAY_WET_FRACTION:.2f}")

    if max_rainless_streak > MAX_RAINLESS_WET_STREAK_H:
        reasons.append(f"rainless_wet_streak_gt_{MAX_RAINLESS_WET_STREAK_H}h")

    return StationSeasonQCResult(
        network=network,
        station_id=station_id,
        crop=crop,
        season_label=season_lbl,
        gap_policy=gap_policy,
        passed=(len(reasons) == 0),
        reasons=tuple(reasons),
        expected_hours=expected_hours,
        valid_hours=valid_hours,
        coverage_frac=round(coverage, 4),
        max_gap_hours=max_gap,
        n_gap_hours=n_gap_hours,
        wet_fraction=round(wet_frac, 4) if wet_frac is not None else None,
        dry_midday_hours=dry_midday_total,
        dry_midday_wet_fraction=round(dry_midday_wet_frac, 4) if dry_midday_wet_frac is not None else None,
        max_rainless_wet_streak_h=max_rainless_streak,
    )


def draw_stratified_lockbox(
    eligible_stations: Sequence[Mapping[str, Any]],
    fraction: float = 0.20,
    min_count: int = 2,
    seed: int = 20261122,
    exclude_ids: Sequence[str] = tuple(V1_INRAE_STATION_IDS),
) -> list[str]:
    """
    Sorteia deterministicamente estacoes para o lockbox, excluindo `exclude_ids`
    (estacoes ja usadas na v1) e estratificando por `region` quando disponivel.
    """
    excluded = set(exclude_ids)
    pool = [
        {"station_id": str(s["station_id"]), "region": str(s.get("region", "default"))}
        for s in eligible_stations
        if str(s["station_id"]) not in excluded
    ]
    pool.sort(key=lambda s: (s["region"], s["station_id"]))
    if len(pool) < min_count:
        raise ValueError(f"pool elegivel ({len(pool)}) menor que o minimo ({min_count})")

    target = max(min_count, round_half_up(fraction * len(pool)))
    target = min(target, len(pool))

    rng = random.Random(seed)
    by_region: dict[str, list[str]] = {}
    for item in pool:
        by_region.setdefault(item["region"], []).append(item["station_id"])

    selected: list[str] = []
    remainders: list[tuple[float, str, list[str]]] = []

    for region in sorted(by_region):
        ids = list(by_region[region])
        rng.shuffle(ids)
        exact = fraction * len(ids)
        k = int(math.floor(exact))
        selected.extend(ids[:k])
        remainders.append((exact - k, region, ids[k:]))

    remainders.sort(key=lambda x: (-x[0], x[1]))
    for _rem, _reg, leftover in remainders:
        if len(selected) >= target:
            break
        if leftover:
            selected.append(leftover.pop(0))

    if len(selected) < target:
        extra_pool = [sid for _rem, _reg, leftover in remainders for sid in leftover]
        rng.shuffle(extra_pool)
        selected.extend(extra_pool[: target - len(selected)])

    return sorted(selected[:target])
