#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_r_coverage.py
======================
Diagnóstico da cobertura do IC 95 % de `r` (que ficou em ~73–77 % na Fase 2,
enquanto a projeção de 7 dias ficou em 93–98 %).

Testa 5 cenários controlados para isolar a causa exata:
1. `well_specified_default`   : verdade logística gerada da priori, ajuste padrão
                                (`forgetting=0.97`, `soft_l1`, `n_obs=8`, 14 d).
2. `well_specified_no_forget` : mesmo cenário com `forgetting=1.0` e `robust_scale=50`
                                (verossimilhança gaussiana exata, sem esquecimento).
3. `well_specified_n16`       : mesmo cenário com mais observações (`n_obs=16`, 30 d,
                                quebrando a colinearidade entre `r` e `y0`).
4. `prior_mismatch_phase2`    : exatamente o gerador usado em `climate_retrospective.py`
                                (onde `y0_true` e `r_true` têm dispersão menor que a priori
                                e `y` é truncado em zero com `severity_sd_pct=0`).
5. `seir_misspecified`        : verdade SEIR (período latente + microclima), medindo
                                a cobertura de `y_7d` e `r_efetivo` (inclinação logística).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import downy_mildew as dm
import epidemiology_assimilation as ea
import leaf_wetness as lw
import osse_benchmark as osse
import simulator as sim

UTC = timezone.utc


def _run_logistic_scenario(
    name: str,
    weather: list[dict],
    disease: str,
    n_trials: int,
    n_obs_days: int,
    step_days: int,
    cfg: ea.AssimilationConfig,
    sample_from_exact_prior: bool,
    censor_at_zero: bool = True,
    seed: int = 777,
) -> dict:
    wdf = ea.weather_frame(weather)
    t0 = wdf.index.min().to_pydatetime() + timedelta(days=1)
    cut = t0 + timedelta(days=n_obs_days)
    t_end = cut + timedelta(days=7)
    base_cfg = ea.AssimilationConfig(fc_sigma0=0.0, fc_sigma_per_day=0.0)
    clock = ea.build_clock(wdf, t0, t_end, disease, base_cfg)
    w_obs = wdf[wdf.index <= pd.Timestamp(cut)]
    w_fc = wdf[(wdf.index > pd.Timestamp(cut)) & (wdf.index <= pd.Timestamp(t_end))]

    params = ea.PATHOGENS[disease]
    rng = np.random.default_rng(seed)

    cov_r = 0
    cov_y0 = 0
    cov_7d = 0
    ess_list = []
    chi2_list = []
    r_errors = []

    for i in range(n_trials):
        if sample_from_exact_prior:
            r_true = float(params["r_prior"] * math.exp(rng.normal(0.0, params["r_prior_sd_log"])))
            # y0 amostrado de logit normal em torno da priori (K=100)
            y0_mu = math.log((params["y0_prior_pct"] / 100.0) / (1.0 - params["y0_prior_pct"] / 100.0))
            logit_y0 = y0_mu + rng.normal(0.0, 1.0)
            y0_true = float(100.0 / (1.0 + math.exp(-logit_y0)))
        else:
            # Exatamente igual ao `climate_retrospective.py`
            r_true = float(params["r_prior"] * math.exp(rng.normal(0.0, 0.35)))
            y0_true = float(np.clip(params["y0_prior_pct"] * math.exp(rng.normal(0.0, 0.35)), 0.08, 1.5))

        obs = []
        for d in range(0, n_obs_days + 1, step_days):
            ts = t0 + timedelta(days=d)
            truth = float(ea.curve("logistic", clock.tau(ts)[0], r_true, y0_true, 100.0))
            sd = math.sqrt(cfg.sigma_floor ** 2 + (cfg.sigma_cv * truth) ** 2)
            y_val = truth + rng.normal(0.0, sd)
            if censor_at_zero:
                y_val = float(np.clip(y_val, 0.0, 100.0))
            else:
                y_val = float(np.clip(y_val, 1e-4, 100.0))
            obs.append({"ts": ts.isoformat(), "severity_pct": y_val, "severity_sd_pct": 0.0})

        res = ea.assimilate(
            unit_id="V11",
            disease=disease,
            observations=obs,
            weather_observed=w_obs,
            weather_forecast=w_fc,
            config=ea.AssimilationConfig(
                forgetting=cfg.forgetting,
                robust_scale=cfg.robust_scale,
                n_draws=cfg.n_draws,
                fc_sigma0=cfg.fc_sigma0,
                fc_sigma_per_day=cfg.fc_sigma_per_day,
                seed=seed + i,
            ),
        )
        r_lo, r_hi = res["params"]["r_ci95"]
        if r_lo <= r_true <= r_hi:
            cov_r += 1
        r_errors.append(math.log(res["params"]["r"]) - math.log(r_true))
        # Checa y_7d
        truth_7d = float(ea.curve("logistic", clock.tau(t_end)[0], r_true, y0_true, 100.0))
        pt = res["projection"][-1]
        if pt["y_lo95"] <= truth_7d <= pt["y_hi95"]:
            cov_7d += 1
        ess_list.append(res["fit"]["posterior_ess"])
        chi2_list.append(res["fit"]["chi2_red"])

    return {
        "scenario": name,
        "n_trials": n_trials,
        "coverage_r_ci95": round(cov_r / n_trials, 4),
        "coverage_7d_ci95": round(cov_7d / n_trials, 4),
        "mean_log_r_bias": round(float(np.mean(r_errors)), 4),
        "median_ess": round(float(np.median(ess_list)), 1),
        "min_ess": round(float(np.min(ess_list)), 1),
        "median_chi2_red": round(float(np.median(chi2_list)), 3),
    }


def _run_seir_scenario(n_trials: int = 50, seed: int = 888) -> dict:
    dm.register_downy_mildew_pathogen()
    weather = dm.fetch_rich_historical_weather("2025-05-01", "2025-06-25", 49.5447, 6.3669)
    wdf = lw.normalize_rich_weather(weather)
    w_epi = osse._weather_for_assimilation_with_lwd(wdf, "cart_kim2002")
    t0 = wdf.index[24].to_pydatetime()
    cut = t0 + timedelta(days=27)
    t_end = cut + timedelta(days=7)
    eval_ts = [t0 + timedelta(days=d) for d in range(0, 28, 3)]
    eval_idx = [int(np.argmin(np.abs(ea._epoch_seconds(wdf.index) - ea._epoch_seconds([ts])[0]))) for ts in eval_ts]
    end_idx = int(np.argmin(np.abs(ea._epoch_seconds(wdf.index) - ea._epoch_seconds([t_end])[0])))

    plots = osse._build_seir_plots(n_trials, seed)
    rng = np.random.default_rng(seed)
    cov_7d = 0
    ess_list = []

    for i, plot in enumerate(plots):
        true_wet = osse._canopy_true_wetness(wdf, plot.micro_dpd_bias_c, plot.wind_shelter, rng)
        traj = osse.simulate_seir_trajectory(wdf, plot, [], true_wet)
        obs = []
        for ts, idx in zip(eval_ts, eval_idx):
            truth = float(traj[idx])
            sd = math.sqrt(0.30 ** 2 + (0.10 * truth) ** 2) / math.sqrt(3.0)
            obs.append({"ts": ts.isoformat(), "severity_pct": float(np.clip(truth + rng.normal(0.0, sd), 0.0, 100.0)), "severity_sd_pct": sd})
        w_obs = w_epi[w_epi.index <= pd.Timestamp(cut)]
        w_fc = w_epi[(w_epi.index > pd.Timestamp(cut)) & (w_epi.index <= pd.Timestamp(t_end))]
        res = ea.assimilate(
            unit_id=plot.plot_id, disease="mildio_videira", observations=obs,
            weather_observed=w_obs, weather_forecast=w_fc,
            config=ea.AssimilationConfig(n_draws=1500, seed=seed + i),
        )
        truth_7d = float(traj[end_idx])
        pt = res["projection"][-1]
        if pt["y_lo95"] <= truth_7d <= pt["y_hi95"]:
            cov_7d += 1
        ess_list.append(res["fit"]["posterior_ess"])

    return {
        "scenario": "seir_misspecified_moselle",
        "n_trials": n_trials,
        "coverage_7d_ci95": round(cov_7d / n_trials, 4),
        "median_ess": round(float(np.median(ess_list)), 1),
    }


def main() -> int:
    weather = sim.generate_synthetic_weather(
        datetime(2025, 11, 1, 0, tzinfo=UTC), days=45, seed=101, mean_temp_c=23.5, mean_rh_pct=84.0
    )
    results = [
        _run_logistic_scenario(
            "1_well_specified_default_8obs", weather, "pinta_preta", 80, 14, 2,
            ea.AssimilationConfig(n_draws=2000), sample_from_exact_prior=True,
        ),
        _run_logistic_scenario(
            "2_well_specified_no_forget_gauss_8obs", weather, "pinta_preta", 80, 14, 2,
            ea.AssimilationConfig(n_draws=2000, forgetting=1.0, robust_scale=50.0, fc_sigma0=0.0, fc_sigma_per_day=0.0),
            sample_from_exact_prior=True,
        ),
        _run_logistic_scenario(
            "3_well_specified_default_16obs_30d", weather, "pinta_preta", 80, 30, 2,
            ea.AssimilationConfig(n_draws=2000), sample_from_exact_prior=True,
        ),
        _run_logistic_scenario(
            "4_phase2_narrow_truth_8obs", weather, "pinta_preta", 80, 14, 2,
            ea.AssimilationConfig(n_draws=2000), sample_from_exact_prior=False,
        ),
        _run_seir_scenario(n_trials=40),
    ]
    out = Path("data/fase2/diagnostico_cobertura_r.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
