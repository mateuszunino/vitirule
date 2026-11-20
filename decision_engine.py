#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decision_engine.py
==================
Motor de decisão agronômica do DSS de pinta-preta e requeima do tomateiro.

Implementa estritamente o contrato da seção 5.4 e as regras da seção 7.4 do
SKILL.md. Os limiares do projeto ficam centralizados em constantes no topo do
módulo (e no dataclass `DecisionConfig`) para facilitar testes de sensibilidade
no simulador sem duplicar lógica.

Este módulo nunca escolhe produto, dose ou intervalo de segurança: apenas
recomenda `spray`, `monitor` ou `none` com as justificativas padronizadas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import epidemiology_assimilation as ea

SCHEMA_VERSION = "1.0"
UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

POT_ID_RE = re.compile(r"^V(0[1-9]|1\d|20)$")
VALID_DISEASES = frozenset(ea.PATHOGENS.keys())
CONTROL_POTS = frozenset(f"V{i:02d}" for i in range(1, 11))
DSS_POTS = frozenset(f"V{i:02d}" for i in range(11, 21))

# Limiares do projeto (seção 7.4 do SKILL.md — a confirmar/calibrar no simulador)
MIN_SPRAY_INTERVAL_DAYS: float = 7.0
TOMCAST_DSV_THRESHOLD: int = 15
WALLIN_7D_THRESHOLD: int = 5
WALLIN_TOTAL_THRESHOLD: int = 18
P_EXCEED_THRESHOLD: float = 0.50
FORECAST_TOMCAST_DSV_7D_MONITOR: int = 10
FORECAST_WALLIN_SV_7D_MONITOR: int = 3


@dataclass(frozen=True)
class DecisionConfig:
    """Limiares configuráveis para a regra de decisão (padrões do SKILL.md 7.4)."""
    min_spray_interval_days: float = MIN_SPRAY_INTERVAL_DAYS
    tomcast_dsv_threshold: int = TOMCAST_DSV_THRESHOLD
    wallin_7d_threshold: int = WALLIN_7D_THRESHOLD
    wallin_total_threshold: int = WALLIN_TOTAL_THRESHOLD
    p_exceed_threshold: float = P_EXCEED_THRESHOLD
    forecast_tomcast_dsv_7d_monitor: int = FORECAST_TOMCAST_DSV_7D_MONITOR
    forecast_wallin_sv_7d_monitor: int = FORECAST_WALLIN_SV_7D_MONITOR


def _parse_aware_dt(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{label} inválido: {value!r}")
    if dt.tzinfo is None:
        raise ValueError(f"{label} sem fuso horário: {value!r}. Use ISO 8601 com offset.")
    return dt


def _parse_local_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{label} sem fuso horário: {value!r}")
        return value.astimezone(LOCAL_TZ).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if "T" in text or " " in text:
            return _parse_aware_dt(text, label).astimezone(LOCAL_TZ).date()
        return date.fromisoformat(text)
    raise ValueError(f"{label} inválido: {value!r}")


def _extract_last_spray_dt(last_spray: Any) -> Optional[datetime]:
    if last_spray is None:
        return None
    if isinstance(last_spray, dict):
        raw = last_spray.get("applied_at")
        if raw is None:
            return None
        return _parse_aware_dt(raw, "last_spray.applied_at")
    return _parse_aware_dt(last_spray, "last_spray")


def compute_dsv_daily_rows(
    weather: Any,
    station_id: str = "sj_vasos",
    kind: str = "observed",
    rh_threshold: float = 85.0,
    day_start_hour: int = 12,
) -> list[dict]:
    """
    Calcula as linhas diárias compatíveis com a tabela `dsv_daily` usando
    diretamente `epidemiology_assimilation.tomcast_dsv`, `wallin_severity`
    e `leaf_wetness` (sem duplicar tabelas ou regras climáticas).
    """
    if kind not in ("observed", "forecast"):
        raise ValueError(f"kind inválido: {kind!r}. Use 'observed' ou 'forecast'.")
    df = ea.weather_frame(weather)
    if df.empty:
        return []
    dsv_series = ea.tomcast_dsv(df, rh_threshold=rh_threshold, day_start_hour=day_start_hour)
    wallin_series = ea.wallin_severity(df, day_start_hour=day_start_hour)
    df_wet = df.assign(wet=ea.leaf_wetness(df, rh_threshold))
    wet_by_day: dict[str, int] = {}
    for day_ts, block in ea._daily_windows(df_wet, day_start_hour):
        wet_by_day[day_ts.date().isoformat()] = int(block["wet"].sum())

    all_days = sorted(set(dsv_series.index) | set(wallin_series.index) | set(wet_by_day.keys()))
    rows: list[dict] = []
    for day_str in all_days:
        rows.append({
            "station_id": station_id,
            "day": date.fromisoformat(day_str),
            "kind": kind,
            "tomcast_dsv": int(dsv_series.get(day_str, 0)),
            "wallin_sv": int(wallin_series.get(day_str, 0)),
            "wet_hours": int(wet_by_day.get(day_str, 0)),
        })
    return rows


def decide(
    epi_result: dict,
    dsv_daily: Sequence[dict],
    last_spray: Optional[Any] = None,
    transplant_date: Optional[Any] = None,
    now: Optional[Any] = None,
    config: Optional[DecisionConfig] = None,
) -> dict:
    """
    Avalia a recomendação de manejo (`spray`, `monitor` ou `none`) para um vaso.

    Parâmetros
    ----------
    epi_result : dict
        Saída de `epidemiology_assimilation.assimilate` (contrato 5.2).
    dsv_daily : Sequence[dict]
        Linhas da tabela `dsv_daily` (chaves `day`, `tomcast_dsv`, `wallin_sv`,
        opcionalmente `kind`). Apenas registros com `kind == 'observed'`
        (ou sem `kind`) entram no acumulado observado.
    last_spray : dict | datetime | str | None
        Último registro de `spray_events` do vaso (ou timestamp ISO 8601 com fuso).
    transplant_date : date | datetime | str | None
        Data de transplante, usada para acumular DSV/Wallin antes da 1ª aplicação.
    now : datetime | str | None
        Instante da decisão (com fuso). Se omitido, usa o relógio atual em
        `America/Sao_Paulo`.
    config : DecisionConfig | None
        Limiares alternativos (para testes de sensibilidade no simulador).
    """
    cfg = config or DecisionConfig()
    pot_id = epi_result.get("unit_id")
    if not isinstance(pot_id, str) or not POT_ID_RE.match(pot_id):
        raise ValueError(f"pot_id inválido: {pot_id!r}. Esperado V01 a V20.")
    disease = epi_result.get("disease")
    if disease not in VALID_DISEASES:
        raise ValueError(f"doença desconhecida: {disease!r}. Use {sorted(VALID_DISEASES)}.")

    decided_dt = (
        _parse_aware_dt(now, "now").astimezone(LOCAL_TZ)
        if now is not None
        else datetime.now(LOCAL_TZ)
    )
    decided_utc = decided_dt.astimezone(UTC)
    decided_day = decided_dt.date()

    last_spray_dt = _extract_last_spray_dt(last_spray)
    last_spray_day = last_spray_dt.astimezone(LOCAL_TZ).date() if last_spray_dt is not None else None
    days_since_last_spray: Optional[float] = (
        round((decided_utc - last_spray_dt.astimezone(UTC)).total_seconds() / 86_400.0, 3)
        if last_spray_dt is not None
        else None
    )

    tp_day = _parse_local_date(transplant_date, "transplant_date") if transplant_date is not None else None

    observed_days: list[tuple[date, int, int]] = []
    for row in dsv_daily or ():
        kind = row.get("kind", "observed")
        if kind != "observed":
            continue
        row_day = _parse_local_date(row["day"], "dsv_daily.day")
        if row_day <= decided_day:
            observed_days.append((
                row_day,
                int(row.get("tomcast_dsv", 0) or 0),
                int(row.get("wallin_sv", 0) or 0),
            ))

    if last_spray_day is not None:
        dsv_since_last_spray = sum(dsv for d, dsv, _ in observed_days if d > last_spray_day)
    else:
        dsv_since_last_spray = sum(
            dsv for d, dsv, _ in observed_days if tp_day is None or d >= tp_day
        )

    week_start = decided_day - timedelta(days=6)
    wallin_sv_7d = sum(w for d, _, w in observed_days if week_start <= d <= decided_day)
    wallin_total = sum(w for d, _, w in observed_days if tp_day is None or d >= tp_day)

    risk = epi_result.get("risk") or {}
    p_exceed_obj = risk.get("p_exceed") or {}
    p_exceed_raw = p_exceed_obj.get("p")
    p_exceed = None if p_exceed_raw is None else float(p_exceed_raw)

    innovation = epi_result.get("innovation") or {}
    regime_change = bool(innovation.get("regime_change", False))

    forecast_dsv_7d = risk.get("tomcast_dsv_7d")
    forecast_wallin_7d = risk.get("wallin_sv_7d")

    inputs = {
        "dsv_since_last_spray": int(dsv_since_last_spray),
        "wallin_sv_7d": int(wallin_sv_7d),
        "p_exceed": None if p_exceed is None else round(p_exceed, 4),
        "days_since_last_spray": days_since_last_spray,
        "regime_change": regime_change,
    }

    action: str
    reasons: list[str] = []

    # Ordem exata da seção 7.4 do SKILL.md
    if pot_id in CONTROL_POTS:
        # 1. Vaso testemunha (V01-V10): nunca aplica
        action = "none"
        reasons = ["control_pot"]
    elif days_since_last_spray is not None and days_since_last_spray < cfg.min_spray_interval_days:
        # 2. Intervalo mínimo entre aplicações (< 7 dias)
        action = "monitor"
        reasons = ["min_interval"]
    else:
        # 3, 4 e 5: condições de aplicação (`spray`)
        if disease == "pinta_preta" and dsv_since_last_spray >= cfg.tomcast_dsv_threshold:
            reasons.append("dsv_since_last_spray>=15")
        if disease == "requeima":
            if wallin_sv_7d >= cfg.wallin_7d_threshold:
                reasons.append("wallin_7d>=5")
            if last_spray_dt is None and wallin_total >= cfg.wallin_total_threshold:
                reasons.append("wallin_total>=18")
        if p_exceed is not None and p_exceed >= cfg.p_exceed_threshold:
            reasons.append("p_exceed>=0.5")

        if reasons:
            action = "spray"
        else:
            # 6. Monitoramento reforçado (novo vídeo em 2 dias)
            if regime_change:
                reasons.append("regime_change")
            has_forecast_risk = (
                (forecast_dsv_7d is not None and forecast_dsv_7d >= cfg.forecast_tomcast_dsv_7d_monitor)
                or (forecast_wallin_7d is not None and forecast_wallin_7d >= cfg.forecast_wallin_sv_7d_monitor)
            )
            if has_forecast_risk:
                reasons.append("forecast_risk")
            # 7. Caso contrário: none
            action = "monitor" if reasons else "none"

    return {
        "schema_version": SCHEMA_VERSION,
        "pot_id": pot_id,
        "disease": disease,
        "decided_at": decided_dt.isoformat(),
        "action": action,
        "reasons": reasons,
        "inputs": inputs,
    }
