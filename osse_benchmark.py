#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osse_benchmark.py
=================
OSSE rigoroso fora da amostra para o DSS de míldio da videira
(*Plasmopara viticola*), implementando:

1. **Quebra do crime inverso e remoção de vazamento:**
   * Verdade gerada por modelo compartimental **SEIR horário discreto** (4 estágios
     latentes segundo Müller-Sleumer/Goidànich, temperaturas cardinais deslocadas,
     viés/ruído de microclima no dossel e previsão de 7 dias com erro crescente).
   * Parâmetros reais de fungicida desacoplados da regra e do modelo:
     - regra fixa: reposição após chuva >= `15,0 mm` (mínimo 4 d) ou intervalo 7 d;
     - verdade SEIR: lavagem de 50 % com `washoff_mm ~ N(25, 8)` mm, eficácia
       `true_efficacy ~ N(0,76, 0,08)` e meia-vida `true_half_life ~ N(5,5, 1,2)` d.
2. **Ablação limpa em 4 braços (todos com orçamento igual ao do DSS):**
   * `(a) uniform_calendar`         : calendário uniforme com o mesmo nº `N` de sprays;
   * `(b) climate_reactive`         : somente clima observado passado (sem previsão,
                                      sem reposição por chuva, sem assimilação);
   * `(c) climate_forecast_washoff` : clima + previsão de 7 d + bloqueio em semana seca
                                      + reposição por chuva (>= 15 mm), **SEM assimilação**;
   * `(d) closed_loop_dss`          : idêntico a `(c)` + assimilação foliar (`delta_y_7d`,
                                      `p_exceed`, `regime_change`).
   A pergunta principal é **`(d)` contra `(c)`** com o mesmo orçamento e as mesmas
   previsões ruidosas.
3. **Inferência estatística e trade-off honesto:**
   * Diferença pareada com IC 95 % por bootstrap (`B = 5000`) e teste de Wilcoxon
     pareado bilateral (`scipy.stats.wilcoxon`).
   * Trade-off explícito contra o `weekly_calendar`: aplicações economizadas e
     AACPD adicional.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

import downy_mildew as dm
import epidemiology_assimilation as ea
import leaf_wetness as lw

log = logging.getLogger("osse_benchmark")

UTC = timezone.utc


@dataclass(frozen=True)
class SeirPlotParams:
    plot_id: str
    beta_max: float                # taxa máxima de infecção por hora favorável
    initial_exposed: float         # inóculo primário latente (fração 0..1)
    tmin_shift_c: float            # erro de especificação térmica (°C)
    topt_shift_c: float
    micro_dpd_bias_c: float        # viés microclimático de DPD no dossel (°C)
    wind_shelter: float            # atenuação de vento no dossel
    washoff_mm: float = 25.0       # chuva acumulada que lava 50 % (desacoplado dos 15 mm da regra)
    true_efficacy: float = 0.76    # eficácia real no campo (desacoplada dos 0,60 do modelo)
    true_half_life_days: float = 5.5


@dataclass(frozen=True)
class VineyardDecisionConfig:
    """Limiares CONGELADOS antes da avaliação fora da amostra (2022–2024)."""
    min_spray_interval_days: float = 7.0
    washoff_override_mm: float = 15.0      # fixo e diferente da média real (25 ± 8 mm)
    washoff_min_days: float = 4.0
    forecast_sv_7d_threshold: int = 7      # gatilho climático de previsão no DSS
    p_exceed_threshold: float = 0.45       # P(severidade > 5 % em 7 d)
    delta_y_7d_threshold_pct: float = 0.8  # crescimento projetado em 7 d (% severidade)
    action_threshold_pct: float = 5.0
    lwd_method: str = "cart_kim2002"


# --------------------------------------------------------------------------
# Gerador de verdade mecanístico: modelo SEIR horário com má especificação
# --------------------------------------------------------------------------
def _canopy_true_wetness(
    wdf: pd.DataFrame,
    micro_dpd_bias_c: float,
    wind_shelter: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Molhamento real dentro do dossel, diferente da estação meteorológica."""
    perturbed = wdf.copy()
    noise = rng.normal(0.0, 0.35, size=len(perturbed))
    perturbed["dewpoint_c"] = np.minimum(
        perturbed["temp_c"],
        perturbed["dewpoint_c"] - micro_dpd_bias_c + noise,
    )
    if "wind_ms" in perturbed.columns:
        perturbed["wind_ms"] = np.maximum(perturbed["wind_ms"].fillna(1.5) * wind_shelter, 0.05)
    return lw.estimate_leaf_wetness(perturbed, method="cart_kim2002").to_numpy(dtype=float)


def simulate_seir_trajectory(
    wdf: pd.DataFrame,
    plot: SeirPlotParams,
    spray_times_utc: Sequence[datetime],
    true_wet: np.ndarray,
    infectious_days: float = 12.0,
) -> np.ndarray:
    """
    Integra SEIR discreto hora a hora com 4 estágios latentes (Müller-Sleumer /
    Goidànich) e lavagem de fungicida por chuva. Retorna `100 * (I + R)`.
    """
    n = len(wdf)
    temps = wdf["temp_c"].to_numpy(dtype=float)
    rains = np.nan_to_num(wdf["precip_mm"].to_numpy(dtype=float), nan=0.0)
    epochs = ea._epoch_seconds(wdf.index)
    spray_epochs = sorted(ea._epoch_seconds(list(spray_times_utc))) if spray_times_utc else []

    tmin = 8.0 + plot.tmin_shift_c
    topt = 22.0 + plot.topt_shift_c
    tmax = 30.0 + plot.topt_shift_c * 0.5
    g_inf = ea.beta_temperature_response(temps, tmin, topt, tmax)

    k_stages = 4
    gamma_inf = 1.0 / (infectious_days * 24.0)

    E = np.zeros(k_stages, dtype=float)
    E[0] = plot.initial_exposed
    I = 0.0005
    R = 0.0
    S = max(1.0 - E.sum() - I - R, 0.0)

    visible_pct = np.zeros(n, dtype=float)
    active_spray_idx = 0
    rain_since_spray = 0.0
    last_spray_epoch: Optional[float] = None

    for h in range(n):
        t_h = epochs[h]
        while active_spray_idx < len(spray_epochs) and spray_epochs[active_spray_idx] <= t_h:
            last_spray_epoch = spray_epochs[active_spray_idx]
            rain_since_spray = 0.0
            active_spray_idx += 1

        if last_spray_epoch is not None:
            rain_since_spray += rains[h]
            age_days = max((t_h - last_spray_epoch) / 86_400.0, 0.0)
            time_decay = 0.5 ** (age_days / plot.true_half_life_days)
            rain_wash = 0.5 ** (rain_since_spray / plot.washoff_mm)
            protection = plot.true_efficacy * time_decay * rain_wash
        else:
            protection = 0.0

        wet_factor = 0.03 + 0.97 * true_wet[h]
        inoculum = I + 0.00015
        new_inf = plot.beta_max * g_inf[h] * wet_factor * (1.0 - protection) * S * inoculum
        new_inf = min(max(new_inf, 0.0), S)

        inc_day_frac = dm.goidanich_daily_incubation_pct(float(temps[h])) / 100.0
        rate_stage = min(k_stages * inc_day_frac / 24.0, 0.95)

        out_E = E * rate_stage
        E_next = E - out_E
        E_next[0] += new_inf
        E_next[1:] += out_E[:-1]

        newly_infectious = out_E[-1]
        removed = I * gamma_inf

        S = max(S - new_inf, 0.0)
        E = np.maximum(E_next, 0.0)
        I = max(I + newly_infectious - removed, 0.0)
        R = min(R + removed, 1.0)

        visible_pct[h] = float(np.clip(100.0 * (I + R), 0.0, 100.0))

    return visible_pct


def _perturb_forecast(fc_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Erro realista de previsão meteorológica crescente de 1 a 7 dias."""
    if fc_df.empty:
        return fc_df
    out = fc_df.copy()
    n = len(out)
    lead_days = np.arange(1, n + 1, dtype=float) / 24.0
    t_err = np.zeros(n)
    rh_err = np.zeros(n)
    for i in range(n):
        sig_t = 0.5 + 0.30 * lead_days[i]
        sig_rh = 3.0 + 1.3 * lead_days[i]
        t_err[i] = (0.85 * t_err[i - 1] if i > 0 else 0.0) + rng.normal(0.0, sig_t * 0.5)
        rh_err[i] = (0.85 * rh_err[i - 1] if i > 0 else 0.0) + rng.normal(0.0, sig_rh * 0.5)
    out["temp_c"] = out["temp_c"] + t_err
    out["rh_pct"] = np.clip(out["rh_pct"] + rh_err, 10.0, 100.0)
    out["dewpoint_c"] = lw.magnus_dewpoint_c(out["temp_c"].to_numpy(), out["rh_pct"].to_numpy())
    if "wind_ms" in out.columns:
        out["wind_ms"] = np.maximum(out["wind_ms"].fillna(1.5) * rng.lognormal(0.0, 0.20, size=n), 0.1)
    return out


def _weather_for_assimilation_with_lwd(wdf: pd.DataFrame, lwd_method: str) -> pd.DataFrame:
    if wdf.empty:
        return wdf[["temp_c", "rh_pct", "precip_mm"]].copy()
    wet = lw.estimate_leaf_wetness(wdf, method=lwd_method).to_numpy(dtype=float)
    out = wdf[["temp_c", "rh_pct", "precip_mm"]].copy()
    out["rh_pct"] = np.where(wet > 0.5, 95.0, 50.0)
    out["precip_mm"] = np.where(wet > 0.5, out["precip_mm"].fillna(0.0), 0.0)
    return out


# --------------------------------------------------------------------------
# Regras dos braços (b), (c) e (d) da ablação
# --------------------------------------------------------------------------
def decide_climate_reactive(
    obs_daily: pd.DataFrame,
    last_spray: Optional[datetime],
    now: datetime,
    threshold_sv_7d: float,
    min_interval_days: float = 7.0,
) -> bool:
    """Braço (b): somente clima observado passado (sem previsão, sem lavagem, sem assimilação)."""
    if last_spray is not None and (now - last_spray).total_seconds() / 86_400.0 < min_interval_days:
        return False
    sv_obs_7d = float(obs_daily.tail(7)["secondary_sv"].sum()) if not obs_daily.empty else 0.0
    rule_3_10 = bool(obs_daily.tail(3)["rule_3_10"].any()) if not obs_daily.empty else False
    return bool((rule_3_10 and last_spray is None) or (sv_obs_7d >= threshold_sv_7d))


def decide_climate_forecast_washoff(
    obs_daily: pd.DataFrame,
    fc_daily: pd.DataFrame,
    last_spray: Optional[datetime],
    now: datetime,
    cfg: VineyardDecisionConfig,
    threshold_score: float,
    rain_since_last_spray_mm: float = 0.0,
) -> bool:
    """
    Braço (c): EXATAMENTE a mesma mecânica climática/previsão/lavagem do DSS
    (previsão 3d/7d, bloqueio em semana seca, regra 3-10 prevista e reposição
    após chuva >= 15 mm), mas SEM nenhuma medição ou assimilação foliar.
    """
    if last_spray is not None:
        days_since = (now - last_spray).total_seconds() / 86_400.0
        washed_off = rain_since_last_spray_mm >= cfg.washoff_override_mm
        min_gap = cfg.washoff_min_days if washed_off else cfg.min_spray_interval_days
        if days_since < min_gap:
            return False

    sv_fc_7d = float(fc_daily.head(7)["secondary_sv"].sum()) if not fc_daily.empty else 0.0
    sv_fc_3d = float(fc_daily.head(3)["secondary_sv"].sum()) if not fc_daily.empty else 0.0
    rule_3_10_recent = bool(obs_daily.tail(3)["rule_3_10"].any()) if not obs_daily.empty else False
    rule_3_10_fc = bool(fc_daily.head(3)["rule_3_10"].any()) if not fc_daily.empty else False

    incoming_risk = (sv_fc_7d >= 3.0) or (sv_fc_3d >= 2.0) or rule_3_10_fc
    if not incoming_risk:
        return False
    if (rule_3_10_recent or rule_3_10_fc) and last_spray is None:
        return True
    # Pontuação puramente climática de previsão (pondera curto prazo + 7 dias)
    fc_score = sv_fc_7d + 0.5 * sv_fc_3d
    return bool(fc_score >= threshold_score)


def decide_closed_loop_dss(
    epi_result: dict,
    obs_daily: pd.DataFrame,
    fc_daily: pd.DataFrame,
    last_spray: Optional[datetime],
    now: datetime,
    cfg: VineyardDecisionConfig,
    rain_since_last_spray_mm: float = 0.0,
) -> tuple[str, list[str]]:
    """Braço (d): idêntico ao (c) em clima/previsão/lavagem + assimilação foliar."""
    if last_spray is not None:
        days_since = (now - last_spray).total_seconds() / 86_400.0
        washed_off = rain_since_last_spray_mm >= cfg.washoff_override_mm
        min_gap = cfg.washoff_min_days if washed_off else cfg.min_spray_interval_days
        if days_since < min_gap:
            return "monitor", ["min_interval"]

    sv_fc_7d = int(fc_daily.head(7)["secondary_sv"].sum()) if not fc_daily.empty else 0
    sv_fc_3d = int(fc_daily.head(3)["secondary_sv"].sum()) if not fc_daily.empty else 0
    rule_3_10_recent = bool(obs_daily.tail(3)["rule_3_10"].any()) if not obs_daily.empty else False
    rule_3_10_fc = bool(fc_daily.head(3)["rule_3_10"].any()) if not fc_daily.empty else False

    p_exceed = float((epi_result.get("risk", {}).get("p_exceed") or {}).get("p") or 0.0)
    regime_change = bool((epi_result.get("innovation") or {}).get("regime_change", False))
    proj = epi_result.get("projection") or []
    y_now = float(proj[0]["y_median"]) if proj else 0.0
    y_7d = float(proj[-1]["y_median"]) if proj else 0.0
    delta_y_7d = max(y_7d - y_now, 0.0)
    tau_gain_7d = float(epi_result.get("risk", {}).get("tau_gain_7d") or 0.0)

    incoming_risk = (sv_fc_7d >= 3) or (sv_fc_3d >= 2) or (tau_gain_7d >= 1.2) or rule_3_10_fc
    if not incoming_risk:
        return "none", []

    reasons: list[str] = []
    if (rule_3_10_recent or rule_3_10_fc) and last_spray is None:
        reasons.append("rule_3_10_primary")
    if delta_y_7d >= cfg.delta_y_7d_threshold_pct:
        reasons.append("projected_delta_y_7d")
    if p_exceed >= cfg.p_exceed_threshold:
        reasons.append("p_exceed>=threshold")
    if regime_change:
        reasons.append("regime_change_with_risk")
    if sv_fc_7d >= cfg.forecast_sv_7d_threshold or sv_fc_3d >= 5:
        reasons.append("forecast_high_risk")

    return ("spray", reasons) if reasons else ("none", [])


# --------------------------------------------------------------------------
# Geração dos talhões SEIR (sem vazamento com a regra)
# --------------------------------------------------------------------------
def _build_seir_plots(n_plots: int, seed: int) -> list[SeirPlotParams]:
    rng = np.random.default_rng(seed)
    plots: list[SeirPlotParams] = []
    for i in range(1, n_plots + 1):
        plots.append(SeirPlotParams(
            plot_id=f"P{i:03d}",
            beta_max=float(0.055 * math.exp(rng.normal(0.0, 0.25))),
            initial_exposed=float(np.clip(0.0025 * math.exp(rng.normal(0.0, 0.45)), 0.0004, 0.018)),
            tmin_shift_c=float(rng.normal(0.0, 1.2)),
            topt_shift_c=float(rng.normal(0.0, 1.5)),
            micro_dpd_bias_c=float(rng.normal(-0.35, 0.40)),
            wind_shelter=float(np.clip(rng.normal(0.65, 0.12), 0.38, 0.92)),
            # Desacoplado da regra fixa (15 mm) e do modelo (0,60 / 7 d)
            washoff_mm=float(np.clip(rng.normal(25.0, 8.0), 12.0, 48.0)),
            true_efficacy=float(np.clip(rng.normal(0.76, 0.08), 0.55, 0.92)),
            true_half_life_days=float(np.clip(rng.normal(5.5, 1.2), 3.5, 9.0)),
        ))
    return plots


def _run_budget_matched_climate_arm(
    arm: str,
    target_n: int,
    wdf: pd.DataFrame,
    obs_daily_per_step: Sequence[pd.DataFrame],
    fc_daily_per_step: Sequence[pd.DataFrame],
    eval_ts_list: Sequence[datetime],
    cfg: VineyardDecisionConfig,
) -> list[datetime]:
    """
    Executa os braços climáticos `(b)` ou `(c)` de forma estritamente causal em
    uma grade fina de limiares e seleciona o limiar causal cujo total de
    aplicações mais se aproxima de `target_n` (orçamento exato do DSS).
    """
    if target_n <= 0:
        return []
    grid = [round(v * 0.5, 1) for v in range(2, 46)]   # 1.0 a 22.5 em passos de 0.5
    best_sprays: Optional[list[datetime]] = None
    best_gap = 10 ** 9

    for thr in grid:
        sprays: list[datetime] = []
        for eval_ts, obs_d, fc_d in zip(eval_ts_list, obs_daily_per_step, fc_daily_per_step):
            rain_since = 0.0
            if sprays:
                rain_since = float(
                    wdf[(wdf.index > pd.Timestamp(sprays[-1])) & (wdf.index <= pd.Timestamp(eval_ts))]["precip_mm"]
                    .fillna(0.0).sum()
                )
            last_sp = sprays[-1] if sprays else None
            if arm == "climate_reactive":
                fire = decide_climate_reactive(obs_d, last_sp, eval_ts, thr, cfg.min_spray_interval_days)
            else:
                fire = decide_climate_forecast_washoff(obs_d, fc_d, last_sp, eval_ts, cfg, thr, rain_since)
            if fire:
                sprays.append(eval_ts + timedelta(hours=2))
        gap = abs(len(sprays) - target_n)
        if gap < best_gap or (gap == best_gap and best_sprays is not None and len(sprays) <= target_n):
            best_gap = gap
            best_sprays = sprays
            if gap == 0:
                break
    return best_sprays or []


# --------------------------------------------------------------------------
# Worker por talhão (paralelizável entre os núcleos da CPU)
# --------------------------------------------------------------------------
def _evaluate_single_plot(task: dict) -> dict:
    dm.register_downy_mildew_pathogen()
    wdf: pd.DataFrame = task["wdf"]
    station_daily_full: pd.DataFrame = task["station_daily_full"]
    plot: SeirPlotParams = task["plot"]
    true_wet: np.ndarray = task["true_wet"]
    season_start: datetime = task["season_start"]
    season_days: int = task["season_days"]
    eval_ts_list: list[datetime] = task["eval_ts_list"]
    eval_indices: list[int] = task["eval_indices"]
    local_tz_name: str = task["local_tz_name"]
    cfg: VineyardDecisionConfig = task["cfg"]
    seed: int = task["seed"]
    n_draws: int = task["n_draws"]

    tz = ZoneInfo(local_tz_name)
    rng = np.random.default_rng(seed)
    epi_cfg = ea.AssimilationConfig(
        n_draws=n_draws,
        action_threshold_pct=cfg.action_threshold_pct,
        seed=seed,
    )

    # Pré-gera as previsões ruidosas EXATAMENTE uma vez para que (c) e (d) vejam o mesmo ruído!
    obs_daily_steps: list[pd.DataFrame] = []
    fc_raw_steps: list[pd.DataFrame] = []
    fc_daily_steps: list[pd.DataFrame] = []
    for eval_ts in eval_ts_list:
        eval_pd = pd.Timestamp(eval_ts)
        fc_end_pd = eval_pd + pd.Timedelta(hours=168)
        eval_day = eval_ts.astimezone(tz).date()
        obs_daily_steps.append(station_daily_full[station_daily_full["day"] <= eval_day])
        fc_raw = _perturb_forecast(wdf[(wdf.index > eval_pd) & (wdf.index <= fc_end_pd)], rng)
        fc_raw_steps.append(fc_raw)
        fc_daily_steps.append(dm.compute_downy_mildew_daily(fc_raw, lwd_method=cfg.lwd_method, local_tz_name=local_tz_name))

    # Pré-converte clima observado uma única vez para agilizar a assimilação
    w_all_epi = _weather_for_assimilation_with_lwd(wdf, cfg.lwd_method)

    # --- Braço (d): DSS completo (assimilação + previsão 7d + lavagem 15 mm) ---
    sprays_d: list[datetime] = []
    obs_records: list[dict] = []
    prev_state: Optional[dict] = None
    for step_i, (eval_ts, hr_idx, obs_d, fc_raw, fc_d) in enumerate(
        zip(eval_ts_list, eval_indices, obs_daily_steps, fc_raw_steps, fc_daily_steps)
    ):
        traj_now = simulate_seir_trajectory(wdf.iloc[: hr_idx + 1], plot, sprays_d, true_wet[: hr_idx + 1])
        true_sev = float(traj_now[-1])
        sigma = math.sqrt(0.30 ** 2 + (0.10 * true_sev) ** 2) / math.sqrt(3.0)
        meas_sev = float(np.clip(true_sev + rng.normal(0.0, sigma), 0.0, 100.0))
        obs_records.append({
            "ts": eval_ts.isoformat(),
            "severity_pct": round(meas_sev, 4),
            "severity_sd_pct": round(sigma, 4),
        })

        eval_pd = pd.Timestamp(eval_ts)
        w_obs_epi = w_all_epi[w_all_epi.index <= eval_pd]
        w_fc_epi = _weather_for_assimilation_with_lwd(fc_raw, cfg.lwd_method)
        fit_res = ea.assimilate(
            unit_id=plot.plot_id,
            disease="mildio_videira",
            observations=obs_records,
            weather_observed=w_obs_epi,
            weather_forecast=w_fc_epi,
            prev_state=prev_state,
            spray_events=[s.isoformat() for s in sprays_d],
            config=replace(epi_cfg, seed=seed + step_i * 19),
            now=eval_ts,
        )
        prev_state = fit_res["state"]
        rain_since = 0.0
        if sprays_d:
            rain_since = float(
                wdf[(wdf.index > pd.Timestamp(sprays_d[-1])) & (wdf.index <= eval_pd)]["precip_mm"]
                .fillna(0.0).sum()
            )
        action, _ = decide_closed_loop_dss(
            fit_res, obs_d, fc_d, sprays_d[-1] if sprays_d else None, eval_ts, cfg, rain_since
        )
        if action == "spray":
            sprays_d.append(eval_ts + timedelta(hours=2))

    n_budget = len(sprays_d)

    # --- Braço (a): calendário uniforme com orçamento exato `n_budget` ---
    if n_budget > 0:
        step = season_days / float(n_budget)
        sprays_a = [season_start + timedelta(days=round(k * step + 0.5 * step), hours=2) for k in range(n_budget)]
    else:
        sprays_a = []

    # --- Braço (b): clima observado reativo, orçamento igualado a `n_budget` ---
    sprays_b = _run_budget_matched_climate_arm(
        "climate_reactive", n_budget, wdf, obs_daily_steps, fc_daily_steps, eval_ts_list, cfg
    )

    # --- Braço (c): clima + previsão 7d + lavagem 15 mm, SEM assimilação, orçamento igualado ---
    sprays_c = _run_budget_matched_climate_arm(
        "climate_forecast_washoff", n_budget, wdf, obs_daily_steps, fc_daily_steps, eval_ts_list, cfg
    )

    # --- Referências: testemunha e calendário semanal ---
    sprays_weekly = [season_start + timedelta(days=d, hours=2) for d in range(0, season_days, 7)]

    def _score(spray_list: list[datetime]) -> dict:
        traj = simulate_seir_trajectory(wdf, plot, spray_list, true_wet)
        sevs = [float(traj[idx]) for idx in eval_indices]
        return {
            "aacpd": round(ea.aacpd(eval_ts_list, sevs), 4),
            "final_sev": round(sevs[-1], 3),
            "n_sprays": len(spray_list),
        }

    return {
        "plot_id": plot.plot_id,
        "testemunha": _score([]),
        "uniform_calendar": _score(sprays_a),
        "climate_reactive": _score(sprays_b),
        "climate_forecast_washoff": _score(sprays_c),
        "closed_loop_dss": _score(sprays_d),
        "weekly_calendar": _score(sprays_weekly),
    }


# --------------------------------------------------------------------------
# Estatística pareada (Bootstrap IC 95 % + Wilcoxon pareado)
# --------------------------------------------------------------------------
def paired_comparison_stats(
    x: Sequence[float],
    y: Sequence[float],
    n_boot: int = 5000,
    seed: int = 12345,
) -> dict:
    """
    Analisa `diff = x - y` (negativo favorece `x`, pois AACPD menor é melhor).
    Retorna média, mediana, IC 95 % bootstrap, p-valor de Wilcoxon bilateral e taxa de vitórias.
    """
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    diff = xa - ya
    n = len(diff)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boot_means, [2.5, 97.5])

    nonzero = diff[np.abs(diff) > 1e-12]
    if len(nonzero) == 0:
        w_p = 1.0
    else:
        w_p = float(wilcoxon(diff, alternative="two-sided", zero_method="wilcox").pvalue)

    wins = int(np.sum(diff < -1e-9))
    ties = int(np.sum(np.abs(diff) <= 1e-9))
    return {
        "n": int(n),
        "mean_diff": round(float(diff.mean()), 3),
        "median_diff": round(float(np.median(diff)), 3),
        "ci95_bootstrap": [round(float(lo), 3), round(float(hi), 3)],
        "wilcoxon_p": round(w_p, 6),
        "x_wins": f"{wins}/{n}",
        "ties": ties,
        "significant_005": bool(w_p < 0.05),
    }


def _summarize_plot_rows(rows: Sequence[dict]) -> dict:
    arms = (
        "testemunha",
        "uniform_calendar",
        "climate_reactive",
        "climate_forecast_washoff",
        "closed_loop_dss",
        "weekly_calendar",
    )
    strategies: dict[str, dict] = {}
    for arm in arms:
        aacpds = np.array([r[arm]["aacpd"] for r in rows], dtype=float)
        sevs = np.array([r[arm]["final_sev"] for r in rows], dtype=float)
        sprays = np.array([r[arm]["n_sprays"] for r in rows], dtype=float)
        strategies[arm] = {
            "n_plots": len(rows),
            "aacpd_mean": round(float(aacpds.mean()), 3),
            "aacpd_sd": round(float(aacpds.std(ddof=1)) if len(aacpds) > 1 else 0.0, 3),
            "final_sev_mean": round(float(sevs.mean()), 3),
            "sprays_mean": round(float(sprays.mean()), 3),
        }

    get_a = lambda arm: [r[arm]["aacpd"] for r in rows]
    get_s = lambda arm: [r[arm]["n_sprays"] for r in rows]

    contrasts = {
        "d_minus_a_dss_vs_uniform": paired_comparison_stats(get_a("closed_loop_dss"), get_a("uniform_calendar")),
        "d_minus_c_assimilation_value": paired_comparison_stats(get_a("closed_loop_dss"), get_a("climate_forecast_washoff")),
        "d_minus_b_dss_vs_reactive": paired_comparison_stats(get_a("closed_loop_dss"), get_a("climate_reactive")),
        "c_minus_a_forecast_vs_uniform": paired_comparison_stats(get_a("climate_forecast_washoff"), get_a("uniform_calendar")),
        "c_minus_b_forecast_vs_reactive": paired_comparison_stats(get_a("climate_forecast_washoff"), get_a("climate_reactive")),
        "b_minus_a_reactive_vs_uniform": paired_comparison_stats(get_a("climate_reactive"), get_a("uniform_calendar")),
    }

    # Trade-off explícito contra o calendário semanal (Req. 6)
    weekly_a = np.array(get_a("weekly_calendar"), dtype=float)
    weekly_s = np.array(get_s("weekly_calendar"), dtype=float)
    tradeoffs: dict[str, dict] = {}
    for arm in ("closed_loop_dss", "climate_forecast_washoff", "climate_reactive"):
        arm_a = np.array(get_a(arm), dtype=float)
        arm_s = np.array(get_s(arm), dtype=float)
        saved = float((weekly_s - arm_s).mean())
        extra_stats = paired_comparison_stats(arm_a, weekly_a)
        tradeoffs[f"{arm}_vs_weekly"] = {
            "sprays_saved_mean": round(saved, 3),
            "sprays_saved_pct": round(100.0 * saved / max(float(weekly_s.mean()), 1e-9), 1),
            "extra_aacpd_mean": extra_stats["mean_diff"],
            "extra_aacpd_ci95": extra_stats["ci95_bootstrap"],
            "extra_aacpd_per_spray_saved": round(extra_stats["mean_diff"] / saved, 3) if saved > 0 else None,
        }

    return {"strategies": strategies, "paired_contrasts": contrasts, "tradeoffs_vs_weekly": tradeoffs}


def run_fair_osse(
    weather: Sequence[dict],
    region_key: str = "moselle_lu",
    season_days: int = 75,
    n_plots: int = 60,
    seed: int = 20240101,
    dec_cfg: Optional[VineyardDecisionConfig] = None,
    n_draws: int = 300,
    max_workers: Optional[int] = None,
) -> dict:
    """Executa a ablação completa em 4 braços de orçamento igual sobre `n_plots` talhões SEIR."""
    cfg = dec_cfg or VineyardDecisionConfig()
    region = dm.VINEYARD_REGIONS[region_key]
    wdf = lw.normalize_rich_weather(weather)
    if wdf.empty:
        raise ValueError("série climática vazia")

    lwd_comparison = lw.compare_lwd_methods(wdf, local_tz_name=region["tz"])
    station_daily_full = dm.compute_downy_mildew_daily(
        wdf, lwd_method=cfg.lwd_method, local_tz_name=region["tz"]
    )

    tz = ZoneInfo(region["tz"])
    t_min = wdf.index.min()
    start_local = t_min.tz_convert(tz).normalize() + pd.Timedelta(hours=9)
    if start_local.tz_convert("UTC") < t_min:
        start_local += pd.Timedelta(days=1)
    season_start = start_local.tz_convert("UTC").to_pydatetime()

    eval_days = list(range(0, season_days + 1, 3))
    eval_ts_list = [season_start + timedelta(days=d) for d in eval_days]
    eval_indices = [
        int(np.argmin(np.abs(ea._epoch_seconds(wdf.index) - ea._epoch_seconds([ts])[0])))
        for ts in eval_ts_list
    ]

    plots = _build_seir_plots(n_plots=n_plots, seed=seed)
    tasks = []
    for i, plot in enumerate(plots):
        true_wet = _canopy_true_wetness(
            wdf, plot.micro_dpd_bias_c, plot.wind_shelter, np.random.default_rng(seed + 10_000 + i)
        )
        tasks.append({
            "wdf": wdf,
            "station_daily_full": station_daily_full,
            "plot": plot,
            "true_wet": true_wet,
            "season_start": season_start,
            "season_days": season_days,
            "eval_ts_list": eval_ts_list,
            "eval_indices": eval_indices,
            "local_tz_name": region["tz"],
            "cfg": cfg,
            "seed": seed + i * 131,
            "n_draws": n_draws,
        })

    workers = max_workers if max_workers is not None else min(max((os.cpu_count() or 2) - 2, 1), len(tasks))
    if workers > 1 and len(tasks) >= 4:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            plot_rows = list(pool.map(_evaluate_single_plot, tasks))
    else:
        plot_rows = [_evaluate_single_plot(t) for t in tasks]

    summary = _summarize_plot_rows(plot_rows)
    return {
        "region": region["name"],
        "region_key": region_key,
        "disease": "mildio_videira",
        "lwd_method": cfg.lwd_method,
        "season_days": season_days,
        "n_plots": n_plots,
        "seed": seed,
        "rule_config": cfg.__dict__,
        "lwd_comparison": lwd_comparison,
        **summary,
        "plot_rows": plot_rows,
    }


def run_out_of_sample_suite(
    regions: Sequence[str] = ("moselle_lu", "bordeaux_fr"),
    years: Sequence[int] = (2022, 2023, 2024),
    n_plots: int = 60,
    season_days: int = 75,
    base_seed: int = 20240101,
    n_draws: int = 300,
) -> dict:
    """
    Executa a bateria oficial fora da amostra (2022–2024, Moselle e Bordeaux,
    60 talhões por região/ano = 360 talhão-safras) com a regra congelada.
    """
    by_cohort: list[dict] = []
    all_rows: list[dict] = []

    for r_i, region_key in enumerate(regions):
        reg = dm.VINEYARD_REGIONS[region_key]
        for y_i, year in enumerate(years):
            start_str = f"{year}-05-01"
            end_str = f"{year}-08-05"
            log.info("Baixando clima real %s %d (%s..%s)...", region_key, year, start_str, end_str)
            weather = dm.fetch_rich_historical_weather(start_str, end_str, reg["latitude"], reg["longitude"])
            cohort_seed = base_seed + r_i * 100_000 + y_i * 10_000
            res = run_fair_osse(
                weather,
                region_key=region_key,
                season_days=season_days,
                n_plots=n_plots,
                seed=cohort_seed,
                n_draws=n_draws,
            )
            all_rows.extend(res["plot_rows"])
            by_cohort.append({
                "region_key": region_key,
                "region": res["region"],
                "year": year,
                "n_plots": n_plots,
                "strategies": res["strategies"],
                "paired_contrasts": res["paired_contrasts"],
                "tradeoffs_vs_weekly": res["tradeoffs_vs_weekly"],
            })

    pooled = _summarize_plot_rows(all_rows)
    return {
        "protocol": "out_of_sample_frozen_ablation_v1",
        "regions": list(regions),
        "years": list(years),
        "n_plots_per_cohort": n_plots,
        "total_plot_seasons": len(all_rows),
        "base_seed": base_seed,
        "rule_config": VineyardDecisionConfig().__dict__,
        "pooled_summary": pooled,
        "cohorts": by_cohort,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="OSSE fora da amostra com ablação em 4 braços.")
    parser.add_argument("--suite-oos", action="store_true",
                        help="roda a bateria completa fora da amostra (Moselle & Bordeaux 2022–2024, 60 talhões)")
    parser.add_argument("--region", choices=sorted(dm.VINEYARD_REGIONS), default="moselle_lu")
    parser.add_argument("--start-date", default="2024-05-01")
    parser.add_argument("--end-date", default="2024-08-05")
    parser.add_argument("--season-days", type=int, default=75)
    parser.add_argument("--n-plots", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20240101)
    parser.add_argument("--n-draws", type=int, default=300)
    parser.add_argument("--out-json", default="data/fase2/osse_oos_2022_2024.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.suite_oos:
        res = run_out_of_sample_suite(
            n_plots=args.n_plots, season_days=args.season_days,
            base_seed=args.seed, n_draws=args.n_draws,
        )
    else:
        reg = dm.VINEYARD_REGIONS[args.region]
        weather = dm.fetch_rich_historical_weather(args.start_date, args.end_date, reg["latitude"], reg["longitude"])
        res = run_fair_osse(
            weather, region_key=args.region, season_days=args.season_days,
            n_plots=args.n_plots, seed=args.seed, n_draws=args.n_draws,
        )
        res.pop("plot_rows", None)

    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
