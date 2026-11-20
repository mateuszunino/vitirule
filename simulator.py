#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
simulator.py
============
Simulador de circuito fechado do DSS de doenças foliares do tomateiro
(BRIEFING.md seção 5.3).

Substitui temporariamente as plantas reais até a Fase 4, mantendo os mesmos
identificadores (`V01`-`V20` e `V01-F1`-`V20-F3`), contratos JSON e tabelas do
`SKILL.md`. Todo dado gerado é marcado com `simulated = true`.

Fluxo por dia de avaliação (a cada 2 ou 3 dias):
    planta virtual (clima real + sprays) -> 3 medições foliares com ruído
    -> aggregate_leaves_to_pot -> assimilate (clima obs + prev 7d)
    -> decision_engine.decide -> spray_event (se action == "spray")
    -> volta para a planta virtual e para a próxima assimilação.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import db
import decision_engine as de
import epidemiology_assimilation as ea
import weather_collector as wc

log = logging.getLogger("simulator")

UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


@dataclass
class SimulationConfig:
    disease: str = "pinta_preta"
    season_days: int = 42
    eval_cadence_days: tuple[int, ...] = (2, 3)   # alterna 2 e 3 dias (SKILL.md seção 1)
    true_model: str = "logistic"                  # "logistic" | "gompertz"
    r_pot_sd_log: float = 0.25                    # variação entre vasos em torno da priori
    y0_pot_sd_log: float = 0.30
    leaf_rel_sd: float = 0.12                     # heterogeneidade entre folhas do mesmo vaso
    vision_sigma_floor: float = 0.30              # BRIEFING.md 5.3: ~0,3 pp + 10 % da severidade
    vision_sigma_cv: float = 0.10
    spray_delay_hours: int = 2
    station_id: str = "sj_vasos"
    seed: int = 20261119
    n_draws: int = 1000                           # menor que 4000 padrão para acelerar simulações em lote
    decision_config: de.DecisionConfig = field(default_factory=de.DecisionConfig)
    epi_config: Optional[ea.AssimilationConfig] = None


@dataclass
class VirtualPot:
    pot_id: str
    treatment: str        # "testemunha" | "dss" | "calendario_semanal"
    r_true: float
    y0_true: float
    leaf_multipliers: dict[str, float]


# --------------------------------------------------------------------------
# Fontes de clima para o simulador
# --------------------------------------------------------------------------
def load_weather_from_csv(path: str | Path, epagri_tz: str = "America/Sao_Paulo") -> list[dict]:
    """
    Carrega clima horário a partir de um CSV da Epagri/Ciram (usando
    `weather_collector.EpagriProvider.parse_csv`) ou de um CSV genérico com
    colunas `ts, temp_c, rh_pct, precip_mm`.
    """
    csv_path = Path(path)
    with open(csv_path, encoding="utf-8-sig", errors="replace") as fh:
        sample = "".join(fh.readline() for _ in range(5))
    if "DataHorario" in sample:
        settings = wc.Settings(epagri_tz=epagri_tz)
        provider = wc.EpagriProvider(settings, requests.Session())
        records = [wc.clean(r) for r in provider.parse_csv(csv_path)]
        return [
            {
                "ts": r.ts.isoformat(),
                "temp_c": r.temp_c,
                "rh_pct": r.rh_pct,
                "precip_mm": r.precip_mm if r.precip_mm is not None else 0.0,
            }
            for r in records
            if r.usable()
        ]

    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_ts = row.get("ts") or row.get("timestamp")
            if not raw_ts:
                continue
            ts = db.ensure_utc(raw_ts, "csv.ts")
            temp = wc.to_float(row.get("temp_c"))
            rh = wc.to_float(row.get("rh_pct"))
            precip = wc.to_float(row.get("precip_mm"))
            rows.append({
                "ts": ts.isoformat(),
                "temp_c": temp,
                "rh_pct": rh,
                "precip_mm": 0.0 if precip is None else precip,
            })
    return rows


def fetch_open_meteo_historical(
    start_date: str | date,
    end_date: str | date,
    latitude: float = -27.5969,
    longitude: float = -48.6367,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Busca clima horário histórico real de São José/SC na API Open-Meteo Archive
    (reanalysis ERA5/ERA5-Land) em UTC.
    """
    s_str = start_date.isoformat() if isinstance(start_date, date) else str(start_date)
    e_str = end_date.isoformat() if isinstance(end_date, date) else str(end_date)
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "tomato-dss-simulator/1.0 (pesquisa; UFSC)")
    resp = sess.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": s_str,
            "end_date": e_str,
            "hourly": "temperature_2m,relative_humidity_2m,precipitation",
            "timezone": "GMT",
            "timeformat": "unixtime",
        },
        timeout=(5.0, 30.0),
    )
    resp.raise_for_status()
    payload = resp.json()
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or [None] * len(times)
    rhs = hourly.get("relative_humidity_2m") or [None] * len(times)
    precips = hourly.get("precipitation") or [None] * len(times)
    out: list[dict] = []
    for i, epoch in enumerate(times):
        ts = datetime.fromtimestamp(int(epoch), tz=UTC)
        out.append({
            "ts": ts.isoformat(),
            "temp_c": wc.to_float(temps[i]),
            "rh_pct": wc.to_float(rhs[i]),
            "precip_mm": wc.to_float(precips[i]),
        })
    return out


def generate_synthetic_weather(
    start: datetime,
    days: int,
    seed: int = 1,
    mean_temp_c: float = 22.0,
    mean_rh_pct: float = 80.0,
    rain_prob: float = 0.08,
) -> list[dict]:
    """Clima sintético horário com ciclo diurno realista (uso em testes offline)."""
    start_utc = db.ensure_utc(start, "start")
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for h in range(1, 24 * days + 1):
        ts = start_utc + timedelta(hours=h)
        local_hour = ts.astimezone(LOCAL_TZ).hour
        wave = math.sin((local_hour - 9) / 24.0 * 2.0 * math.pi)
        rain = float(rng.random() < rain_prob) * float(rng.gamma(2.0, 1.5))
        temp = mean_temp_c + 4.5 * wave + float(rng.normal(0.0, 0.7))
        rh = min(max(mean_rh_pct - 14.0 * wave + (10.0 if rain > 0 else 0.0) + float(rng.normal(0.0, 3.0)), 25.0), 100.0)
        rows.append({
            "ts": ts.isoformat(),
            "temp_c": round(temp, 2),
            "rh_pct": round(rh, 1),
            "precip_mm": round(rain, 2),
        })
    return rows


# --------------------------------------------------------------------------
# Geração das unidades virtuais e circuito fechado
# --------------------------------------------------------------------------
def _build_virtual_pots(
    cfg: SimulationConfig,
    rng: np.random.Generator,
    treatment_override: Optional[str] = None,
) -> list[VirtualPot]:
    params = ea.PATHOGENS[cfg.disease]
    pots: list[VirtualPot] = []
    for i in range(1, 21):
        pot_id = f"V{i:02d}"
        treatment = treatment_override or ("testemunha" if i <= 10 else "dss")
        r_true = float(params["r_prior"] * math.exp(rng.normal(0.0, cfg.r_pot_sd_log)))
        y0_true = float(np.clip(params["y0_prior_pct"] * math.exp(rng.normal(0.0, cfg.y0_pot_sd_log)), 0.05, 2.0))
        leaf_mults = {
            f"{pot_id}-F{f}": float(np.clip(rng.normal(1.0, cfg.leaf_rel_sd), 0.70, 1.35))
            for f in range(1, 4)
        }
        pots.append(VirtualPot(
            pot_id=pot_id,
            treatment=treatment,
            r_true=r_true,
            y0_true=y0_true,
            leaf_multipliers=leaf_mults,
        ))
    return pots


def _evaluation_days(season_days: int, cadence: Sequence[int]) -> list[int]:
    days = [0]
    idx = 0
    while True:
        step = int(cadence[idx % len(cadence)])
        nxt = days[-1] + step
        if nxt > season_days:
            break
        days.append(nxt)
        idx += 1
    return days


def _make_simulated_vision_record(
    leaf_id: str,
    pot_id: str,
    captured_at: datetime,
    severity_pct: float,
    severity_sd_pct: float,
    run_tag: str,
) -> dict:
    """Payload compatível com o contrato 5.1, marcado como simulado."""
    necrosis_pct = round(severity_pct * 0.65, 4)
    chlorosis_pct = round(max(severity_pct - necrosis_pct, 0.0), 4)
    captured_local = captured_at.astimezone(LOCAL_TZ)
    fname = f"{leaf_id}_{captured_local.strftime('%Y%m%dT%H%M')}_sim.mp4"
    sha = hashlib.sha256(f"{run_tag}|{leaf_id}|{captured_at.isoformat()}".encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0",
        "simulated": True,
        "leaf_id": leaf_id,
        "pot_id": pot_id,
        "captured_at": captured_local.isoformat(),
        "video": {"file": fname, "sha256": sha, "n_frames": 120, "fps": 30.0, "width": 1920, "height": 1080},
        "severity_pct": round(severity_pct, 4),
        "severity_sd_pct": round(severity_sd_pct, 4),
        "necrosis_pct": necrosis_pct,
        "chlorosis_pct": chlorosis_pct,
        "leaf_area_cm2": 40.0,
        "lesion_area_mm2": round(40.0 * severity_pct, 4),
        "necrosis_area_mm2": round(40.0 * necrosis_pct, 4),
        "chlorosis_area_mm2": round(40.0 * chlorosis_pct, 4),
        "calibration": {"px_per_cm": 90.0, "ref_square_side_px": 180.0, "ref_square_side_cm": 2.0,
                        "squareness": 1.0, "ok": True},
        "aggregation": {"method": "consensus", "n_keyframes": 4, "n_valid": 4, "n_aligned": 4, "reference_frame": 0},
        "keyframe_selection": {"sharpness_p90": 100.0, "n_blurry": 0, "n_duplicates_dropped": 0},
        "method": {"weights_a": None, "weights_b": None, "device": "cpu", "half": False, "stage_a": "simulated", "stage_b": "simulated"},
        "keyframes": [],
        "quality": {"ok": True, "flags": []},
        "processing_ms": 0,
    }


def _simulate_pots(
    weather: Sequence[dict],
    pots: Sequence[VirtualPot],
    cfg: SimulationConfig,
    rng: np.random.Generator,
    conn=None,
    run_tag: str = "sim",
) -> dict:
    if cfg.disease not in ea.PATHOGENS:
        raise ValueError(f"doença desconhecida: {cfg.disease!r}")
    weather_df = ea.weather_frame(weather)
    if weather_df.empty:
        raise ValueError("série climática vazia para a simulação")

    epi_cfg = cfg.epi_config or ea.AssimilationConfig(n_draws=cfg.n_draws, seed=cfg.seed)
    t_min_weather = weather_df.index.min()
    t_max_weather = weather_df.index.max()
    # Inicia às 09:00 locais do primeiro dia coberto pelo clima
    first_local = t_min_weather.tz_convert(LOCAL_TZ).normalize() + pd.Timedelta(hours=9)
    if first_local.tz_convert("UTC") < t_min_weather:
        first_local += pd.Timedelta(days=1)
    season_start = first_local.tz_convert("UTC").to_pydatetime()
    transplant_date = season_start.astimezone(LOCAL_TZ).date()

    available_days = int((t_max_weather.to_pydatetime() - season_start).total_seconds() // 86_400)
    effective_season_days = min(cfg.season_days, max(available_days - 7, 1))
    eval_days = _evaluation_days(effective_season_days, cfg.eval_cadence_days)
    if len(eval_days) < 2:
        raise ValueError(
            f"janela climática muito curta ({available_days} dias) para simular a estação "
            f"(precisa de pelo menos 10 dias com horizonte de previsão)."
        )

    # Pré-calcula tabela dsv_daily observada para toda a janela climática
    all_dsv_rows = de.compute_dsv_daily_rows(
        weather_df, station_id=cfg.station_id, kind="observed", rh_threshold=epi_cfg.rh_wet_threshold
    )
    if conn is not None and all_dsv_rows:
        db.upsert_dsv_daily(conn, all_dsv_rows)

    pot_states: dict[str, Optional[dict]] = {p.pot_id: None for p in pots}
    pot_sprays: dict[str, list[datetime]] = {p.pot_id: [] for p in pots}
    pot_leaf_assessments: dict[str, list[dict]] = {p.pot_id: [] for p in pots}
    pot_fits: dict[str, list[dict]] = {p.pot_id: [] for p in pots}
    pot_decisions: dict[str, list[dict]] = {p.pot_id: [] for p in pots}
    pot_true_series: dict[str, list[dict]] = {p.pot_id: [] for p in pots}

    for day_offset in eval_days:
        eval_ts = season_start + timedelta(days=day_offset)
        eval_pd = pd.Timestamp(eval_ts)
        fc_end_pd = eval_pd + pd.Timedelta(hours=epi_cfg.horizon_hours)
        obs_weather = weather_df[weather_df.index <= eval_pd]
        fc_weather = weather_df[(weather_df.index > eval_pd) & (weather_df.index <= fc_end_pd)]
        eval_local_day = eval_ts.astimezone(LOCAL_TZ).date()
        dsv_up_to_now = [r for r in all_dsv_rows if r["day"] <= eval_local_day]

        for pot in pots:
            # 1. Severidade verdadeira do vaso na hora da avaliação (inclui efeito de sprays anteriores)
            true_clock = ea.build_clock(
                obs_weather, season_start, eval_ts, cfg.disease, epi_cfg, pot_sprays[pot.pot_id]
            )
            tau_now = float(true_clock.tau(eval_ts)[0])
            true_pot_sev = float(ea.curve(cfg.true_model, tau_now, pot.r_true, pot.y0_true, 100.0))
            pot_true_series[pot.pot_id].append({
                "ts": eval_ts.isoformat(),
                "day": day_offset,
                "true_severity_pct": round(true_pot_sev, 4),
                "tau": round(tau_now, 4),
            })

            # 2. Gera 3 medições foliares ruidosas (BRIEFING.md 5.3 item 4)
            for leaf_id, mult in pot.leaf_multipliers.items():
                true_leaf_sev = float(np.clip(true_pot_sev * mult, 0.0, 100.0))
                sigma = math.sqrt(cfg.vision_sigma_floor ** 2 + (cfg.vision_sigma_cv * true_leaf_sev) ** 2)
                measured = float(np.clip(true_leaf_sev + rng.normal(0.0, sigma), 0.0, 100.0))
                kf_sd = round(float(max(0.05, 0.35 * sigma)), 4)
                vision_payload = _make_simulated_vision_record(
                    leaf_id, pot.pot_id, eval_ts, measured, kf_sd, run_tag
                )
                pot_leaf_assessments[pot.pot_id].append({
                    "leaf_id": leaf_id,
                    "ts": eval_ts.isoformat(),
                    "severity_pct": vision_payload["severity_pct"],
                    "severity_sd_pct": kf_sd,
                    "simulated": True,
                })
                if conn is not None:
                    db.insert_video_assessment(
                        conn,
                        vision_payload,
                        video_path=f"simulated/{vision_payload['video']['file']}",
                        simulated=True,
                    )

            # 3. Agrega as 3 folhas para o vaso e assimila
            pot_obs = ea.aggregate_leaves_to_pot(pot_leaf_assessments[pot.pot_id])
            fit_res = ea.assimilate(
                unit_id=pot.pot_id,
                disease=cfg.disease,
                observations=pot_obs,
                weather_observed=obs_weather,
                weather_forecast=fc_weather,
                prev_state=pot_states[pot.pot_id],
                spray_events=[s.isoformat() for s in pot_sprays[pot.pot_id]],
                config=replace(epi_cfg, seed=cfg.seed + day_offset * 31 + int(pot.pot_id[1:])),
                now=eval_ts,
            )
            fit_res["simulated"] = True
            pot_states[pot.pot_id] = fit_res["state"]
            pot_fits[pot.pot_id].append(fit_res)
            if conn is not None:
                db.insert_epi_fit(conn, fit_res, simulated=True)

            # 4. Motor de decisão (ou calendário semanal, se modo comparativo)
            last_spray = pot_sprays[pot.pot_id][-1] if pot_sprays[pot.pot_id] else None
            if pot.treatment == "calendario_semanal":
                days_since = (
                    (eval_ts - last_spray).total_seconds() / 86_400.0
                    if last_spray is not None
                    else None
                )
                should_spray = days_since is None or days_since >= 7.0
                decision_res = {
                    "schema_version": de.SCHEMA_VERSION,
                    "pot_id": pot.pot_id,
                    "disease": cfg.disease,
                    "decided_at": eval_ts.astimezone(LOCAL_TZ).isoformat(),
                    "action": "spray" if should_spray else "none",
                    "reasons": ["weekly_calendar"] if should_spray else [],
                    "inputs": {
                        "dsv_since_last_spray": 0,
                        "wallin_sv_7d": 0,
                        "p_exceed": fit_res["risk"]["p_exceed"]["p"],
                        "days_since_last_spray": None if days_since is None else round(days_since, 3),
                        "regime_change": bool((fit_res.get("innovation") or {}).get("regime_change", False)),
                    },
                    "simulated": True,
                }
            else:
                decision_res = de.decide(
                    epi_result=fit_res,
                    dsv_daily=dsv_up_to_now,
                    last_spray=last_spray,
                    transplant_date=transplant_date,
                    now=eval_ts,
                    config=cfg.decision_config,
                )
                decision_res["simulated"] = True
                if conn is not None:
                    db.insert_decision(conn, decision_res, simulated=True)

            pot_decisions[pot.pot_id].append(decision_res)

            # 5. Registra aplicação recomendada -> volta para o modelo e planta virtual
            if decision_res["action"] == "spray" and pot.treatment != "testemunha":
                spray_ts = eval_ts + timedelta(hours=cfg.spray_delay_hours)
                pot_sprays[pot.pot_id].append(spray_ts)
                if conn is not None:
                    db.insert_spray_event(
                        conn,
                        pot_id=pot.pot_id,
                        applied_at=spray_ts,
                        product="fungicida_simulado",
                        dose="padrao",
                        notes="aplicacao gerada pelo simulador",
                        simulated=True,
                    )

    # Resumo por vaso e por tratamento
    pot_summaries: list[dict] = []
    series_rows: list[dict] = []
    for pot in pots:
        pot_obs = ea.aggregate_leaves_to_pot(pot_leaf_assessments[pot.pot_id])
        times = [o["ts"] for o in pot_obs]
        sevs = [o["severity_pct"] for o in pot_obs]
        obs_aacpd = ea.aacpd(times, sevs) if len(pot_obs) > 1 else 0.0

        true_times = [r["ts"] for r in pot_true_series[pot.pot_id]]
        true_sevs = [r["true_severity_pct"] for r in pot_true_series[pot.pot_id]]
        true_aacpd = ea.aacpd(true_times, true_sevs) if len(true_sevs) > 1 else 0.0

        first_day = db.ensure_utc(times[0]).astimezone(LOCAL_TZ).date().isoformat()
        last_day = db.ensure_utc(times[-1]).astimezone(LOCAL_TZ).date().isoformat()
        t0_utc = db.ensure_utc(times[0])
        for o in pot_obs:
            dt_days = (db.ensure_utc(o["ts"]) - t0_utc).total_seconds() / 86_400.0
            series_rows.append({
                "pot_id": pot.pot_id,
                "treatment": pot.treatment,
                "disease": cfg.disease,
                "day": dt_days,
                "severity_pct": float(o["severity_pct"]),
                "simulated": True,
            })

        pot_summaries.append({
            "pot_id": pot.pot_id,
            "treatment": pot.treatment,
            "disease": cfg.disease,
            "r_true": round(pot.r_true, 5),
            "y0_true": round(pot.y0_true, 5),
            "aacpd": round(obs_aacpd, 8),
            "aacpd_true": round(true_aacpd, 8),
            "final_severity_pct": round(sevs[-1], 4),
            "n_avaliacoes": len(pot_obs),
            "n_sprays": len(pot_sprays[pot.pot_id]),
            "primeira_data": first_day,
            "ultima_data": last_day,
            "simulated": True,
        })

    by_treatment: dict[str, dict] = {}
    for treatment in sorted({p["treatment"] for p in pot_summaries}):
        grp = [p for p in pot_summaries if p["treatment"] == treatment]
        aacpds = np.array([p["aacpd"] for p in grp], dtype=float)
        sprays = np.array([p["n_sprays"] for p in grp], dtype=float)
        by_treatment[treatment] = {
            "n_pots": len(grp),
            "aacpd_mean": round(float(aacpds.mean()), 4),
            "aacpd_sd": round(float(aacpds.std(ddof=1)) if len(grp) > 1 else 0.0, 4),
            "sprays_mean": round(float(sprays.mean()), 3),
            "sprays_total": int(sprays.sum()),
        }

    return {
        "simulated": True,
        "disease": cfg.disease,
        "season_start": season_start.astimezone(LOCAL_TZ).isoformat(),
        "eval_days": eval_days,
        "summary_by_treatment": by_treatment,
        "pots": pot_summaries,
        "pot_series": series_rows,
    }


def run_simulation(
    weather: Sequence[dict],
    config: Optional[SimulationConfig] = None,
    conn=None,
) -> dict:
    """
    Executa o ensaio simulado completo com 20 vasos (`V01`-`V10` testemunha,
    `V11`-`V20` DSS) sobre a série climática fornecida.
    """
    cfg = config or SimulationConfig()
    rng = np.random.default_rng(cfg.seed)
    pots = _build_virtual_pots(cfg, rng)
    return _simulate_pots(weather, pots, cfg, rng, conn=conn, run_tag=f"trial_{cfg.seed}_{cfg.disease}")


def compare_strategies(
    weather: Sequence[dict],
    config: Optional[SimulationConfig] = None,
) -> dict:
    """
    Compara três estratégias (`testemunha`, `calendario_semanal` e `dss`) nos
    mesmos 10 vasos virtuais sorteados (V11-V20) para eliminar ruído entre grupos
    (BRIEFING.md Fase 3, item 5).
    """
    cfg = config or SimulationConfig()
    base_rng = np.random.default_rng(cfg.seed)
    base_pots = _build_virtual_pots(cfg, base_rng)[10:]   # V11..V20 (10 vasos)

    comparison: dict[str, dict] = {}
    all_pots_rows: list[dict] = []
    all_series_rows: list[dict] = []
    for strategy in ("testemunha", "calendario_semanal", "dss"):
        if strategy == "testemunha":
            # Mantém V01-V10 para testemunha (SKILL.md seção 1), preservando os mesmos parâmetros pareados
            strat_pots = [
                replace(
                    p,
                    pot_id=f"V{idx:02d}",
                    treatment=strategy,
                    leaf_multipliers={
                        f"V{idx:02d}-F{f}": p.leaf_multipliers[f"{p.pot_id}-F{f}"]
                        for f in range(1, 4)
                    },
                )
                for idx, p in enumerate(base_pots, start=1)
            ]
        else:
            strat_pots = [replace(p, treatment=strategy) for p in base_pots]
        strat_rng = np.random.default_rng(cfg.seed + 1000)   # mesmo ruído de medição entre estratégias
        res = _simulate_pots(
            weather, strat_pots, cfg, strat_rng, conn=None, run_tag=f"cmp_{strategy}_{cfg.seed}"
        )
        comparison[strategy] = res["summary_by_treatment"][strategy]
        all_pots_rows.extend(res["pots"])
        all_series_rows.extend(res["pot_series"])

    return {
        "simulated": True,
        "disease": cfg.disease,
        "strategies": comparison,
        "pots": all_pots_rows,
        "pot_series": all_series_rows,
    }


def export_simulation_aacpd_csv(
    sim_result: dict,
    output_path: str | Path,
    series_output_path: Optional[str | Path] = None,
) -> Path:
    """
    Exporta `r/dados/aacpd_por_vaso.csv` no formato exato da seção 9 do SKILL.md:
    `pot_id, treatment, disease, aacpd, n_avaliacoes, primeira_data, ultima_data`.
    Opcionalmente grava também as séries diárias por vaso para validação Python vs R.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=db.AACPD_CSV_COLUMNS)
        writer.writeheader()
        for p in sim_result["pots"]:
            writer.writerow({k: p[k] for k in db.AACPD_CSV_COLUMNS})

    if series_output_path is not None:
        s_out = Path(series_output_path)
        s_out.parent.mkdir(parents=True, exist_ok=True)
        with open(s_out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=("pot_id", "treatment", "disease", "day", "severity_pct", "simulated")
            )
            writer.writeheader()
            writer.writerows(sim_result["pot_series"])
    return out


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Simulador de circuito fechado do DSS de tomateiro.")
    parser.add_argument("--disease", choices=sorted(ea.PATHOGENS), default="pinta_preta")
    parser.add_argument("--season-days", type=int, default=42)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--weather-csv", help="CSV da Epagri ou CSV horário (ts,temp_c,rh_pct,precip_mm)")
    parser.add_argument("--open-meteo-start", help="data inicial YYYY-MM-DD para buscar histórico real no Open-Meteo")
    parser.add_argument("--open-meteo-end", help="data final YYYY-MM-DD para buscar histórico real no Open-Meteo")
    parser.add_argument("--compare", action="store_true", help="compara testemunha, calendario_semanal e dss")
    parser.add_argument("--export-aacpd", default="r/dados/aacpd_por_vaso.csv")
    parser.add_argument("--export-series", help="CSV opcional com a série diária por vaso para checar AUDPC no R")
    parser.add_argument("--save-db", action="store_true", help="grava no PostgreSQL marcado com simulated=true")
    parser.add_argument("--output-json", help="grava resumo JSON completo neste arquivo")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.weather_csv:
        weather = load_weather_from_csv(args.weather_csv)
    elif args.open_meteo_start and args.open_meteo_end:
        weather = fetch_open_meteo_historical(args.open_meteo_start, args.open_meteo_end)
    else:
        start_dt = datetime(2025, 10, 1, 0, 0, tzinfo=UTC)
        weather = generate_synthetic_weather(start_dt, days=args.season_days + 14, seed=args.seed)

    cfg = SimulationConfig(disease=args.disease, season_days=args.season_days, seed=args.seed)
    conn = None
    if args.save_db:
        conn = db.get_connection()
        db.init_db(conn)

    try:
        if args.compare:
            result = compare_strategies(weather, cfg)
        else:
            result = run_simulation(weather, cfg, conn=conn)
    finally:
        if conn is not None:
            conn.close()

    if args.export_aacpd:
        export_simulation_aacpd_csv(result, args.export_aacpd, series_output_path=args.export_series)

    summary_out = {k: v for k, v in result.items() if k != "pot_series"}
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(summary_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary_out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
