#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semireal_osse.py
================
OSSE **semirreal** nas 4 estações vitícolas da rede INRAE AgroClim
(DOI: 10.57745/BQ0BWB) e teste com erro de molhamento calibrado em Moselle (LU).

Objetivo (regra congelada em `a562ccc`, NENHUM parâmetro alterado):
1. **Verdade SEIR semirreal:** epidemia movida por temperatura, chuva e
   **molhamento foliar MEDIDO PELO SENSOR REAL** da estação INRAE (`h` em [0, 1]).
2. **Entrada operacional da regra (`om_v1_T10`, `om_v2_T10`):** a regra lê
   **apenas a reanálise Open-Meteo** no mesmo `(lat, lon)` + erro crescente de
   previsão de 7 dias, sem ver a estação nem o sensor -> mede **quanto do ganho
   de Pareto sobrevive** sob erro real de ~4 h/dia no molhamento.
3. **Entrada com estação local (`st_v1_T10`, `st_v2_T10`):** a regra lê `T, UR,
   chuva, vento` medidos na estação INRAE (ainda sem ler o sensor de molhamento)
   + previsão ruidosa de 7 dias -> quantifica o ganho direto de trocar reanálise
   por estação meteorológica local.
4. **Calibração empírica do erro de molhamento (viés, MAE e autocorrelação lag-1):**
   aplicada em regiões sem sensor real (ex.: Moselle, Luxemburgo).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import downy_mildew as dm
import epidemiology_assimilation as ea
import leaf_wetness as lw
import lwd_sensor_validation as lsv
import osse_benchmark as osse
import pareto_analysis as pa

log = logging.getLogger("semireal_osse")

UTC = timezone.utc


# --------------------------------------------------------------------------
# 1. Calibração empírica do erro de molhamento (Open-Meteo vs. sensor INRAE)
# --------------------------------------------------------------------------
def measure_reanalysis_wetness_error(
    lwd_method: str = "rh90_hysteresis",
    year_start: int = 2019,
    year_end: int = 2024,
) -> dict[str, Any]:
    """
    Mede viés horário/diário, MAE diário e autocorrelação horária lag-1 do erro
    `e_t = w_open_meteo(t) - h_sensor(t)` nas 4 estações vitícolas do INRAE.
    """
    all_err: list[np.ndarray] = []
    daily_diffs: list[np.ndarray] = []
    lag1_corrs: list[float] = []
    p_true_given_om1_num = p_true_given_om1_den = 0.0
    p_true_given_om0_num = p_true_given_om0_den = 0.0

    for st in lsv.INRAE_STATIONS:
        st_df = lsv.load_inrae_station(st["file"], year_start, year_end)
        st_df = st_df[(st_df.index.month >= 5) & (st_df.index.month <= 8)]
        om_df = lsv._fetch_open_meteo_for_range(st["lat"], st["lon"], st_df.index.min(), st_df.index.max())
        common = st_df.index.intersection(om_df.index)
        h_obs = st_df.loc[common, "sensor_hours"].to_numpy(dtype=float)
        w_om = lw.estimate_leaf_wetness(om_df.loc[common], method=lwd_method, wind_height_m=10.0).to_numpy(dtype=float)

        err = w_om - h_obs
        all_err.append(err)
        if len(err) > 2 and np.std(err[:-1]) > 0 and np.std(err[1:]) > 0:
            lag1_corrs.append(float(np.corrcoef(err[:-1], err[1:])[0, 1]))

        p_true_given_om1_num += float(h_obs[w_om > 0.5].sum())
        p_true_given_om1_den += float((w_om > 0.5).sum())
        p_true_given_om0_num += float(h_obs[w_om <= 0.5].sum())
        p_true_given_om0_den += float((w_om <= 0.5).sum())

        tz = ZoneInfo(st["tz"])
        day_lbl = (common.tz_convert(tz) - pd.Timedelta(hours=12)).normalize()
        d_obs = pd.Series(h_obs, index=common).groupby(day_lbl).sum()
        d_om = pd.Series(w_om, index=common).groupby(day_lbl).sum()
        daily_diffs.append((d_om - d_obs).to_numpy(dtype=float))

    err_cat = np.concatenate(all_err)
    day_cat = np.concatenate(daily_diffs)
    return {
        "lwd_method": lwd_method,
        "period": f"{year_start}-{year_end} (May-Aug, 4 INRAE stations)",
        "n_hours": int(len(err_cat)),
        "hourly_bias_om_minus_sensor": round(float(err_cat.mean()), 4),
        "hourly_error_sd": round(float(err_cat.std(ddof=1)), 4),
        "hourly_error_lag1_autocorr": round(float(np.mean(lag1_corrs)), 4),
        "daily_bias_h": round(float(day_cat.mean()), 3),
        "daily_mae_h": round(float(np.mean(np.abs(day_cat))), 3),
        "p_sensor_wet_given_om_wet": round(p_true_given_om1_num / max(p_true_given_om1_den, 1.0), 4),
        "p_sensor_wet_given_om_dry": round(p_true_given_om0_num / max(p_true_given_om0_den, 1.0), 4),
    }


def simulate_calibrated_true_wetness(
    om_wdf: pd.DataFrame,
    error_model: dict[str, Any],
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Para locais sem sensor (ex.: Moselle), gera molhamento verdadeiro do dossel
    aplicando o erro empírico calibrado no INRAE (viés, desvio e persistência
    horária AR(1) lag-1) sobre a estimativa da reanálise Open-Meteo.
    """
    w_om = lw.estimate_leaf_wetness(om_wdf, method=error_model["lwd_method"], wind_height_m=10.0).to_numpy(dtype=float)
    n = len(w_om)
    phi = float(np.clip(error_model["hourly_error_lag1_autocorr"], 0.1, 0.95))
    mu = float(error_model["hourly_bias_om_minus_sensor"])   # om - true => true = om - err
    sd = float(error_model["hourly_error_sd"])
    innov_sd = sd * float(np.sqrt(max(1.0 - phi ** 2, 1e-4)))

    err = np.zeros(n, dtype=float)
    err[0] = mu + rng.normal(0.0, sd)
    for t in range(1, n):
        err[t] = mu + phi * (err[t - 1] - mu) + rng.normal(0.0, innov_sd)

    # Probabilidade condicional latente suavizada preservando viés e persistência real
    p_base = np.where(
        w_om > 0.5,
        error_model["p_sensor_wet_given_om_wet"],
        error_model["p_sensor_wet_given_om_dry"],
    )
    # Adiciona componente AR(1) centrado em 0 para gerar surtos persistentes de erro
    latent = p_base - (err - mu) * 0.55
    return np.clip(latent, 0.0, 1.0)


# --------------------------------------------------------------------------
# 2. Worker do OSSE semirreal (verdade = sensor real; regra = Open-Meteo vs Estação)
# --------------------------------------------------------------------------
def _semireal_plot_worker(task: dict) -> dict:
    truth_wdf: pd.DataFrame = task["truth_wdf"]          # clima real da estação INRAE
    true_wet: np.ndarray = task["true_wet"]              # molhamento MEDIDO pelo sensor INRAE [0..1]
    om_wdf: pd.DataFrame = task["om_wdf"]                # reanálise Open-Meteo no mesmo (lat, lon)
    om_daily_full: pd.DataFrame = task["om_daily_full"]
    st_daily_full: Optional[pd.DataFrame] = task["st_daily_full"]
    plot: osse.SeirPlotParams = task["plot"]
    season_start: datetime = task["season_start"]
    season_days: int = task["season_days"]
    eval_ts_list: list[datetime] = task["eval_ts_list"]
    eval_indices: list[int] = task["eval_indices"]
    local_tz_name: str = task["local_tz_name"]
    lwd_method: str = task["lwd_method"]
    threshold: float = task["threshold"]
    seed: int = task["seed"]

    tz = ZoneInfo(local_tz_name)
    rng = np.random.default_rng(seed)
    v1_cfg = osse.VineyardDecisionConfig(lwd_method=lwd_method)
    v2_cfg = pa.ResidualGateConfig(lwd_method=lwd_method)

    # Pré-gera previsões ruidosas de 7 d sobre o Open-Meteo (usadas pelo modo operacional)
    om_obs_steps: list[pd.DataFrame] = []
    om_fc_steps: list[pd.DataFrame] = []
    st_obs_steps: list[pd.DataFrame] = []
    st_fc_steps: list[pd.DataFrame] = []

    for eval_ts in eval_ts_list:
        eval_pd = pd.Timestamp(eval_ts)
        fc_end_pd = eval_pd + pd.Timedelta(hours=168)
        eval_day = eval_ts.astimezone(tz).date()

        om_obs_steps.append(om_daily_full[om_daily_full["day"] <= eval_day])
        fc_om_raw = osse._perturb_forecast(om_wdf[(om_wdf.index > eval_pd) & (om_wdf.index <= fc_end_pd)], rng)
        om_fc_steps.append(dm.compute_downy_mildew_daily(fc_om_raw, lwd_method=lwd_method, local_tz_name=local_tz_name))

        if st_daily_full is not None:
            st_obs_steps.append(st_daily_full[st_daily_full["day"] <= eval_day])
            # Estação local também recebe previsão meteorológica com erro realista (Open-Meteo ruidoso)
            st_fc_steps.append(om_fc_steps[-1])

    def _score(sprays: list[datetime]) -> dict:
        traj = osse.simulate_seir_trajectory(truth_wdf, plot, sprays, true_wet)
        sevs = [float(traj[idx]) for idx in eval_indices]
        return {"aacpd": round(ea.aacpd(eval_ts_list, sevs), 4), "n_sprays": len(sprays)}

    def _run_rule(source_wdf: pd.DataFrame, obs_steps, fc_steps, version: str) -> list[datetime]:
        sprays: list[datetime] = []
        for eval_ts, obs_d, fc_d in zip(eval_ts_list, obs_steps, fc_steps):
            rain_since = 0.0
            if sprays:
                rain_since = float(
                    source_wdf[(source_wdf.index > pd.Timestamp(sprays[-1])) & (source_wdf.index <= pd.Timestamp(eval_ts))]["precip_mm"]
                    .fillna(0.0).sum()
                )
            last_sp = sprays[-1] if sprays else None
            if version == "v1":
                fire = osse.decide_climate_forecast_washoff(obs_d, fc_d, last_sp, eval_ts, v1_cfg, threshold, rain_since)
            else:
                fire = pa.decide_forecast_residual_gate(obs_d, fc_d, last_sp, eval_ts, threshold, rain_since, v2_cfg)
            if fire:
                sprays.append(eval_ts + timedelta(hours=2))
        return sprays

    out: dict[str, Any] = {"plot_id": plot.plot_id, "testemunha": _score([])}
    for interval in pa.FIXED_CALENDAR_INTERVALS:
        sprays = [season_start + timedelta(days=d, hours=2) for d in range(0, season_days, interval)]
        out[f"cal_{interval}d"] = _score(sprays)

    # Modo operacional: regra vê APENAS Open-Meteo (sem sensor e sem estação!)
    out["om_v1_T10"] = _score(_run_rule(om_wdf, om_obs_steps, om_fc_steps, "v1"))
    out["om_v2_T10"] = _score(_run_rule(om_wdf, om_obs_steps, om_fc_steps, "v2"))

    # Modo estação local: regra vê T/UR/chuva/vento da estação INRAE (ainda SEM ler sensor LWD!)
    if st_daily_full is not None:
        out["st_v1_T10"] = _score(_run_rule(truth_wdf, st_obs_steps, st_fc_steps, "v1"))
        out["st_v2_T10"] = _score(_run_rule(truth_wdf, st_obs_steps, st_fc_steps, "v2"))

    return out


def _summarize_semireal(rows: Sequence[dict], has_station_arm: bool = True) -> dict:
    cal_keys = [f"cal_{d}d" for d in pa.FIXED_CALENDAR_INTERVALS]
    rule_keys = ["om_v1_T10", "om_v2_T10"] + (["st_v1_T10", "st_v2_T10"] if has_station_arm else [])

    def _agg(key: str) -> dict:
        mean_a, ci_a = pa._boot_mean_ci95([r[key]["aacpd"] for r in rows])
        mean_s, ci_s = pa._boot_mean_ci95([r[key]["n_sprays"] for r in rows])
        return {
            "strategy": key,
            "n_plots": len(rows),
            "sprays_mean": mean_s,
            "sprays_ci95": ci_s,
            "aacpd_mean": mean_a,
            "aacpd_ci95": ci_a,
        }

    cals = [_agg(k) for k in cal_keys]
    rules = []
    paired_vs_cal: dict[str, dict] = {}
    for k in rule_keys:
        pt = _agg(k)
        ref = pa._interpolate_calendar_frontier(cals, pt["sprays_mean"])
        pt["calendar_frontier_aacpd"] = ref
        pt["delta_vs_calendar_frontier"] = None if ref is None else round(pt["aacpd_mean"] - ref, 3)
        rules.append(pt)
        closest = min(cals, key=lambda c: abs(c["sprays_mean"] - pt["sprays_mean"]))["strategy"]
        st_cmp = osse.paired_comparison_stats(
            [r[k]["aacpd"] for r in rows],
            [r[closest]["aacpd"] for r in rows],
        )
        st_cmp["compared_to"] = closest
        st_cmp["delta_sprays"] = round(pt["sprays_mean"] - next(c["sprays_mean"] for c in cals if c["strategy"] == closest), 3)
        paired_vs_cal[k] = st_cmp

    return {
        "testemunha": _agg("testemunha"),
        "calendars": cals,
        "rules": rules,
        "paired_vs_closest_calendar": paired_vs_cal,
    }


def run_semireal_inrae(
    years: Sequence[int] = (2019, 2020, 2021, 2022, 2023, 2024),
    lwd_method: str = "rh90_hysteresis",
    n_plots: int = 50,
    season_days: int = 75,
    base_seed: int = 20250501,
) -> dict:
    """Roda OSSE semirreal nas 4 estações INRAE (verdade = sensor real, regra = Open-Meteo vs Estação)."""
    workers = max((os.cpu_count() or 2) - 2, 1)
    all_rows: list[dict] = []
    cohorts: list[dict] = []

    for s_i, st in enumerate(lsv.INRAE_STATIONS):
        full_st = lsv.load_inrae_station(st["file"], min(years), max(years))
        tz = ZoneInfo(st["tz"])
        for y_i, year in enumerate(years):
            start_utc = pd.Timestamp(f"{year}-05-01T00:00:00Z")
            end_utc = pd.Timestamp(f"{year}-08-05T23:00:00Z")
            st_sub = full_st[(full_st.index >= start_utc) & (full_st.index <= end_utc)].copy()
            if len(st_sub) < 1800:
                continue
            log.info("Semirreal INRAE %s %d ...", st["name"], year)
            om_rows = dm.fetch_rich_historical_weather(f"{year}-05-01", f"{year}-08-05", st["lat"], st["lon"])
            om_wdf = lw.normalize_rich_weather(om_rows)

            common = st_sub.index.intersection(om_wdf.index)
            truth_wdf = st_sub.loc[common, ["temp_c", "rh_pct", "precip_mm", "wind_ms", "rad_wm2"]].copy()
            truth_wdf["dewpoint_c"] = lw.magnus_dewpoint_c(
                truth_wdf["temp_c"].to_numpy(), truth_wdf["rh_pct"].to_numpy()
            )
            true_wet = np.clip(st_sub.loc[common, "sensor_hours"].to_numpy(dtype=float), 0.0, 1.0)
            om_aligned = om_wdf.loc[common].copy()

            om_daily_full = dm.compute_downy_mildew_daily(om_aligned, lwd_method=lwd_method, local_tz_name=st["tz"])
            # Estação INRAE mede vento a 2 m -> calcula LWD com wind_height_m=2.0 via normalize
            st_daily_full = dm.compute_downy_mildew_daily(truth_wdf, lwd_method=lwd_method, local_tz_name=st["tz"])

            t_min = common.min()
            start_local = t_min.tz_convert(tz).normalize() + pd.Timedelta(hours=9)
            if start_local.tz_convert("UTC") < t_min:
                start_local += pd.Timedelta(days=1)
            season_start = start_local.tz_convert("UTC").to_pydatetime()
            eval_ts_list = [season_start + timedelta(days=d) for d in range(0, season_days + 1, 3)]
            eval_indices = [
                int(np.argmin(np.abs(ea._epoch_seconds(common) - ea._epoch_seconds([ts])[0])))
                for ts in eval_ts_list
            ]

            c_seed = base_seed + s_i * 100_000 + y_i * 10_000
            plots = osse._build_seir_plots(n_plots=n_plots, seed=c_seed)
            tasks = [
                {
                    "truth_wdf": truth_wdf,
                    "true_wet": true_wet,
                    "om_wdf": om_aligned,
                    "om_daily_full": om_daily_full,
                    "st_daily_full": st_daily_full,
                    "plot": p,
                    "season_start": season_start,
                    "season_days": season_days,
                    "eval_ts_list": eval_ts_list,
                    "eval_indices": eval_indices,
                    "local_tz_name": st["tz"],
                    "lwd_method": lwd_method,
                    "threshold": pa.FROZEN_OPERATING_THRESHOLD,
                    "seed": c_seed + i * 131,
                }
                for i, p in enumerate(plots)
            ]
            with ProcessPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(_semireal_plot_worker, tasks))
            all_rows.extend(rows)
            cohorts.append({
                "station_id": st["id"],
                "name": st["name"],
                "year": year,
                "summary": _summarize_semireal(rows, has_station_arm=True),
            })

    return {
        "protocol": "semireal_inrae_sensor_truth_frozen_T10",
        "lwd_method": lwd_method,
        "years": list(years),
        "n_plots_per_cohort": n_plots,
        "total_plot_seasons": len(all_rows),
        "pooled": _summarize_semireal(all_rows, has_station_arm=True),
        "cohorts": cohorts,
    }


def run_moselle_calibrated_error(
    error_model: dict[str, Any],
    years: Sequence[int] = (2016, 2017, 2018),
    n_plots: int = 60,
    season_days: int = 75,
    base_seed: int = 20169901,
) -> dict:
    """
    Roda Moselle (LU) sem sensor usando perturbação de molhamento calibrada nos
    erros reais medidos no INRAE (viés, MAE e autocorrelação lag-1).
    """
    workers = max((os.cpu_count() or 2) - 2, 1)
    reg = dm.VINEYARD_REGIONS["moselle_lu"]
    tz = ZoneInfo(reg["tz"])
    lwd_method = error_model["lwd_method"]
    all_rows: list[dict] = []
    cohorts: list[dict] = []

    for y_i, year in enumerate(years):
        log.info("Moselle erro calibrado %d ...", year)
        om_rows = dm.fetch_rich_historical_weather(f"{year}-05-01", f"{year}-08-05", reg["latitude"], reg["longitude"])
        om_wdf = lw.normalize_rich_weather(om_rows)
        om_daily_full = dm.compute_downy_mildew_daily(om_wdf, lwd_method=lwd_method, local_tz_name=reg["tz"])

        t_min = om_wdf.index.min()
        start_local = t_min.tz_convert(tz).normalize() + pd.Timedelta(hours=9)
        if start_local.tz_convert("UTC") < t_min:
            start_local += pd.Timedelta(days=1)
        season_start = start_local.tz_convert("UTC").to_pydatetime()
        eval_ts_list = [season_start + timedelta(days=d) for d in range(0, season_days + 1, 3)]
        eval_indices = [
            int(np.argmin(np.abs(ea._epoch_seconds(om_wdf.index) - ea._epoch_seconds([ts])[0])))
            for ts in eval_ts_list
        ]

        c_seed = base_seed + y_i * 10_000
        plots = osse._build_seir_plots(n_plots=n_plots, seed=c_seed)
        tasks = [
            {
                "truth_wdf": om_wdf,
                "true_wet": simulate_calibrated_true_wetness(om_wdf, error_model, np.random.default_rng(c_seed + 5000 + i)),
                "om_wdf": om_wdf,
                "om_daily_full": om_daily_full,
                "st_daily_full": None,
                "plot": p,
                "season_start": season_start,
                "season_days": season_days,
                "eval_ts_list": eval_ts_list,
                "eval_indices": eval_indices,
                "local_tz_name": reg["tz"],
                "lwd_method": lwd_method,
                "threshold": pa.FROZEN_OPERATING_THRESHOLD,
                "seed": c_seed + i * 131,
            }
            for i, p in enumerate(plots)
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_semireal_plot_worker, tasks))
        all_rows.extend(rows)
        cohorts.append({"region": reg["name"], "year": year, "summary": _summarize_semireal(rows, has_station_arm=False)})

    return {
        "protocol": "moselle_calibrated_reanalysis_error_frozen_T10",
        "error_model": error_model,
        "years": list(years),
        "total_plot_seasons": len(all_rows),
        "pooled": _summarize_semireal(all_rows, has_station_arm=False),
        "cohorts": cohorts,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="OSSE semirreal (sensor INRAE) + Moselle com erro calibrado.")
    parser.add_argument("--lwd-method", choices=lw.VALID_METHODS, default="rh90_hysteresis")
    parser.add_argument("--n-plots", type=int, default=50)
    parser.add_argument("--out-json", default="data/fase2/semireal_inrae_osse.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    err_model = measure_reanalysis_wetness_error(lwd_method=args.lwd_method)
    inrae_res = run_semireal_inrae(lwd_method=args.lwd_method, n_plots=args.n_plots)
    moselle_res = run_moselle_calibrated_error(err_model, n_plots=60)

    report = {
        "empirical_reanalysis_error": err_model,
        "inrae_semireal_sensor_truth": inrae_res,
        "moselle_calibrated_error": moselle_res,
    }
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== ERRO EMPIRICO DA REANALISE (4 estacoes INRAE) ===")
    print(json.dumps(err_model, indent=2))
    print("\n=== OSSE SEMIRREAL INRAE (verdade = SENSOR REAL, N=%d) ===" % inrae_res["total_plot_seasons"])
    print(json.dumps(inrae_res["pooled"], indent=2))
    print("\n=== MOSELLE COM ERRO CALIBRADO (2016-2018, N=%d) ===" % moselle_res["total_plot_seasons"])
    print(json.dumps(moselle_res["pooled"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
