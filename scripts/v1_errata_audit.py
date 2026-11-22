#!/usr/bin/env python3
"""
scripts/v1_errata_audit.py
==========================
Auditoria reproduzivel para a Errata v1.0.1.

Executa os codigos CONGELADOS da v1 (`lwd_sensor_validation.py`,
`semireal_osse.py` e `economics.py`) sem alterar nenhum parametro, excluindo
apenas as estacoes-safra reprovadas pelo controle de qualidade cego
`vitirule_v2.qc` na janela da videira (1 abr a 30 set).
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import downy_mildew as dm
import economics as econ
import epidemiology_assimilation as ea
import leaf_wetness as lw
import lwd_sensor_validation as lsv
import osse_benchmark as osse
import pareto_analysis as pa
import semireal_osse as sr
from vitirule_v2.qc import evaluate_station_season_qc
from vitirule_v2.sensors import load_inrae_records, load_polito_records


def compute_v2_grapevine_qc_mask() -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, dict[str, Any]]]:
    """Aplica `vitirule_v2.qc` na janela da videira (Abr-Set) as estacoes da v1."""
    inrae_qc: dict[tuple[str, int], dict[str, Any]] = {}
    for st in lsv.INRAE_STATIONS:
        recs = load_inrae_records(ROOT / st["file"], year_min=2019, year_max=2024)
        for yr in range(2019, 2025):
            yr_recs = [r for r in recs if yr - 1 <= r.ts.year <= yr + 1]
            res = evaluate_station_season_qc(
                raw_records=yr_recs,
                network="inrae",
                station_id=st["id"],
                crop="grapevine",
                season_year=yr,
                tz_name=st["tz"],
                hemisphere="northern_hemisphere",
            )
            inrae_qc[(st["id"], yr)] = res.to_dict()

    polito_sites = json.loads((ROOT / "data/lwd_sensors/polito/sites.json").read_text(encoding="utf-8"))["sites"]
    polito_qc: dict[str, dict[str, Any]] = {}
    for site in sorted(polito_sites, key=lambda x: x["ref"]):
        recs = load_polito_records(ROOT / "data/lwd_sensors/polito" / site["ref"])
        yr = sorted({r.ts.year for r in recs})[0]
        res = evaluate_station_season_qc(
            raw_records=recs,
            network="polito",
            station_id=site["ref"],
            crop="grapevine",
            season_year=yr,
            tz_name="Europe/Rome",
            hemisphere="northern_hemisphere",
        )
        polito_qc[site["ref"]] = res.to_dict()
    return inrae_qc, polito_qc


def run_filtered_lwd_validation(
    inrae_qc: dict[tuple[str, int], dict[str, Any]],
    polito_qc: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Re-executa `lwd_sensor_validation` apenas nas estacoes-safra aprovadas no QC."""
    inrae_reports: list[dict[str, Any]] = []
    for st in lsv.INRAE_STATIONS:
        passing_years = [yr for yr in (2022, 2023, 2024) if inrae_qc[(st["id"], yr)]["passed"]]
        if not passing_years:
            continue
        dfs = [lsv.load_inrae_station(ROOT / st["file"], yr, yr) for yr in passing_years]
        st_df = pd.concat(dfs).sort_index()
        om_dfs = [
            lsv._fetch_open_meteo_for_range(st["lat"], st["lon"], d.index.min(), d.index.max())
            for d in dfs
        ]
        om_df = pd.concat(om_dfs).sort_index()
        om_df = om_df[~om_df.index.duplicated(keep="last")]
        res_station = lsv._eval_estimators(st_df, st_df["leaf_wet_sensor"], wind_height_m=2.0, local_tz_name=st["tz"])
        res_om = lsv._eval_estimators(om_df, st_df["leaf_wet_sensor"], wind_height_m=10.0, local_tz_name=st["tz"])
        inrae_reports.append({
            "station_id": st["id"],
            "name": st["name"],
            "passing_years": passing_years,
            "station_weather": res_station,
            "open_meteo_reanalysis": res_om,
        })

    polito_sites = json.loads((ROOT / "data/lwd_sensors/polito/sites.json").read_text(encoding="utf-8"))["sites"]
    polito_reports: list[dict[str, Any]] = []
    for site in sorted(polito_sites, key=lambda x: x["ref"]):
        if not polito_qc[site["ref"]]["passed"]:
            continue
        st_df = lsv.load_polito_site(ROOT / "data/lwd_sensors/polito" / site["ref"], wet_threshold=20.0)
        om_df = lsv._fetch_open_meteo_for_range(site["lat"], site["lon"], st_df.index.min(), st_df.index.max())
        res_station = lsv._eval_estimators(st_df, st_df["leaf_wet_sensor"], wind_height_m=2.0, local_tz_name="Europe/Rome")
        res_om = lsv._eval_estimators(om_df, st_df["leaf_wet_sensor"], wind_height_m=10.0, local_tz_name="Europe/Rome")
        polito_reports.append({
            "station_id": site["ref"],
            "station_weather": res_station,
            "open_meteo_reanalysis": res_om,
        })

    return {
        "inrae_qc_passed": {
            "n_station_years": sum(len(r["passing_years"]) for r in inrae_reports),
            "pooled_station_weather": lsv._aggregate_network(inrae_reports, "station_weather"),
            "pooled_open_meteo_reanalysis": lsv._aggregate_network(inrae_reports, "open_meteo_reanalysis"),
            "stations": inrae_reports,
        },
        "polito_qc_passed": {
            "n_sites": len(polito_reports),
            "passing_sites": [r["station_id"] for r in polito_reports],
            "pooled_station_weather": lsv._aggregate_network(polito_reports, "station_weather"),
            "pooled_open_meteo_reanalysis": lsv._aggregate_network(polito_reports, "open_meteo_reanalysis"),
        },
    }


def run_filtered_semireal(
    inrae_qc: dict[tuple[str, int], dict[str, Any]],
    lwd_method: str = "rh90_hysteresis",
    n_plots: int = 50,
    season_days: int = 75,
    base_seed: int = 20250501,
) -> dict[str, Any]:
    """Re-executa `semireal_osse` congelado preservando exatamente as sementes originais."""
    years = (2019, 2020, 2021, 2022, 2023, 2024)
    workers = max((os.cpu_count() or 2) - 2, 1)

    # 1. Erro empirico da reanalise (May-Aug) apenas nas estacoes-safra aprovadas no QC
    all_err: list[np.ndarray] = []
    daily_diffs: list[np.ndarray] = []
    lag1_corrs: list[float] = []
    p_om1_num = p_om1_den = p_om0_num = p_om0_den = 0.0

    # 2. OSSE semirreal INRAE preservando indices (s_i, y_i) originais para sementes identicas
    all_rows: list[dict] = []
    rows_19_21: list[dict] = []
    rows_22_24: list[dict] = []
    cohorts: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for s_i, st in enumerate(lsv.INRAE_STATIONS):
            full_st = lsv.load_inrae_station(ROOT / st["file"], min(years), max(years))
            tz = ZoneInfo(st["tz"])
            for y_i, year in enumerate(years):
                if not inrae_qc[(st["id"], year)]["passed"]:
                    continue

                # Erro empirico May-Aug
                st_ma = full_st[(full_st.index.year == year) & (full_st.index.month >= 5) & (full_st.index.month <= 8)].copy()
                om_ma_rows = dm.fetch_rich_historical_weather(f"{year}-05-01", f"{year}-08-31", st["lat"], st["lon"])
                om_ma = lw.normalize_rich_weather(om_ma_rows)
                common_ma = st_ma.index.intersection(om_ma.index)
                h_obs = st_ma.loc[common_ma, "sensor_hours"].to_numpy(dtype=float)
                w_om = lw.estimate_leaf_wetness(om_ma.loc[common_ma], method=lwd_method, wind_height_m=10.0).to_numpy(dtype=float)
                err = w_om - h_obs
                all_err.append(err)
                if len(err) > 2 and np.std(err[:-1]) > 0 and np.std(err[1:]) > 0:
                    lag1_corrs.append(float(np.corrcoef(err[:-1], err[1:])[0, 1]))
                p_om1_num += float(h_obs[w_om > 0.5].sum())
                p_om1_den += float((w_om > 0.5).sum())
                p_om0_num += float(h_obs[w_om <= 0.5].sum())
                p_om0_den += float((w_om <= 0.5).sum())
                day_lbl = (common_ma.tz_convert(tz) - pd.Timedelta(hours=12)).normalize()
                daily_diffs.append(
                    (pd.Series(w_om, index=common_ma).groupby(day_lbl).sum()
                     - pd.Series(h_obs, index=common_ma).groupby(day_lbl).sum()).to_numpy(dtype=float)
                )

                # OSSE semirreal May 1 - Aug 5
                start_utc = pd.Timestamp(f"{year}-05-01T00:00:00Z")
                end_utc = pd.Timestamp(f"{year}-08-05T23:00:00Z")
                st_sub = full_st[(full_st.index >= start_utc) & (full_st.index <= end_utc)].copy()
                om_aligned = om_ma[(om_ma.index >= start_utc) & (om_ma.index <= end_utc)].copy()
                common = st_sub.index.intersection(om_aligned.index)
                truth_wdf = st_sub.loc[common, ["temp_c", "rh_pct", "precip_mm", "wind_ms", "rad_wm2"]].copy()
                truth_wdf["dewpoint_c"] = lw.magnus_dewpoint_c(
                    truth_wdf["temp_c"].to_numpy(), truth_wdf["rh_pct"].to_numpy()
                )
                true_wet = np.clip(st_sub.loc[common, "sensor_hours"].to_numpy(dtype=float), 0.0, 1.0)
                om_sub = om_aligned.loc[common].copy()

                om_daily_full = dm.compute_downy_mildew_daily(om_sub, lwd_method=lwd_method, local_tz_name=st["tz"])
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
                        "om_wdf": om_sub,
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
                rows = list(pool.map(sr._semireal_plot_worker, tasks))

                all_rows.extend(rows)
                if year <= 2021:
                    rows_19_21.extend(rows)
                else:
                    rows_22_24.extend(rows)
                cohorts.append({
                    "station_id": st["id"],
                    "name": st["name"],
                    "year": year,
                    "summary": sr._summarize_semireal(rows, has_station_arm=True),
                })

    err_cat = np.concatenate(all_err)
    day_cat = np.concatenate(daily_diffs)
    err_model = {
        "lwd_method": lwd_method,
        "period": f"2019-2024 (May-Aug, {len(cohorts)} QC-passed INRAE station-years)",
        "n_hours": int(len(err_cat)),
        "hourly_bias_om_minus_sensor": round(float(err_cat.mean()), 4),
        "hourly_error_sd": round(float(err_cat.std(ddof=1)), 4),
        "hourly_error_lag1_autocorr": round(float(np.mean(lag1_corrs)), 4),
        "daily_bias_h": round(float(day_cat.mean()), 3),
        "daily_mae_h": round(float(np.mean(np.abs(day_cat))), 3),
        "p_sensor_wet_given_om_wet": round(p_om1_num / max(p_om1_den, 1.0), 4),
        "p_sensor_wet_given_om_dry": round(p_om0_num / max(p_om0_den, 1.0), 4),
    }

    def _extrapolated_frontier(cals: list[dict], sprays: float) -> float:
        pts = sorted((c["sprays_mean"], c["aacpd_mean"]) for c in cals)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if x0 <= sprays <= x1:
                return y0 + (y1 - y0) * (sprays - x0) / max(x1 - x0, 1e-9)
        if sprays < pts[0][0]:
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            return y0 + (y1 - y0) * (sprays - x0) / max(x1 - x0, 1e-9)
        x0, y0 = pts[-2]
        x1, y1 = pts[-1]
        return y1 + (y1 - y0) * (sprays - x1) / max(x1 - x0, 1e-9)

    # Decomposicao por coorte e correlacao entre pulverizacoes e pressao
    untreated_vals = []
    om_sprays_vals = []
    all_deltas = []
    interp_deltas = []
    st_all_deltas = []
    for c in cohorts:
        s = c["summary"]
        untreated_vals.append(s["testemunha"]["aacpd_mean"])
        om_r = next(r for r in s["rules"] if r["strategy"] == "om_v1_T10")
        st_r = next(r for r in s["rules"] if r["strategy"] == "st_v1_T10")
        om_sprays_vals.append(om_r["sprays_mean"])
        om_delta = om_r["delta_vs_calendar_frontier"]
        if om_delta is None:
            om_delta = round(om_r["aacpd_mean"] - _extrapolated_frontier(s["calendars"], om_r["sprays_mean"]), 3)
        st_delta = st_r["delta_vs_calendar_frontier"]
        if st_delta is None:
            st_delta = round(st_r["aacpd_mean"] - _extrapolated_frontier(s["calendars"], st_r["sprays_mean"]), 3)
        all_deltas.append(om_delta)
        st_all_deltas.append(st_delta)
        if 6.0 <= om_r["sprays_mean"] <= 11.0 and om_r["delta_vs_calendar_frontier"] is not None:
            interp_deltas.append(om_r["delta_vs_calendar_frontier"])

    r_val, p_val = stats.pearsonr(untreated_vals, om_sprays_vals)

    # Moselle com o modelo de erro recalibrado nas coortes limpas do INRAE
    moselle_res = sr.run_moselle_calibrated_error(err_model, n_plots=60)

    # Superficie economica (economics.py) sobre o pooled limpo
    pooled_summary = sr._summarize_semireal(all_rows, has_station_arm=True)
    econ_res = {
        "unconstrained": econ.sensitivity_grid(pooled_summary, enforce_eu_copper=False, copper_dose_kg_ha=0.50),
        "eu_copper_050": econ.sensitivity_grid(pooled_summary, enforce_eu_copper=True, copper_dose_kg_ha=0.50),
    }

    return {
        "empirical_reanalysis_error": err_model,
        "inrae_semireal_qc_passed": {
            "n_cohorts": len(cohorts),
            "total_plot_seasons": len(all_rows),
            "pooled": pooled_summary,
            "unseen_2019_2021": sr._summarize_semireal(rows_19_21, has_station_arm=True),
            "selection_2022_2024": sr._summarize_semireal(rows_22_24, has_station_arm=True),
            "per_cohort_stats": {
                "n_cohorts": len(cohorts),
                "all_cohorts_delta_mean": round(float(np.mean(all_deltas)), 3),
                "all_cohorts_delta_median": round(float(np.median(all_deltas)), 3),
                "all_cohorts_n_below_frontier": int(sum(d < 0 for d in all_deltas)),
                "n_interpolated_6_to_11": len(interp_deltas),
                "interpolated_delta_mean": round(float(np.mean(interp_deltas)), 3) if interp_deltas else None,
                "interpolated_delta_median": round(float(np.median(interp_deltas)), 3) if interp_deltas else None,
                "interpolated_n_below_frontier": int(sum(d < 0 for d in interp_deltas)),
                "st_all_cohorts_delta_mean": round(float(np.mean(st_all_deltas)), 3),
                "pearson_r_sprays_vs_untreated": round(float(r_val), 4),
                "pearson_p_sprays_vs_untreated": float(p_val),
            },
            "cohorts": cohorts,
        },
        "moselle_calibrated_error": moselle_res,
        "economics_pooled_qc_passed": econ_res,
    }


def main() -> int:
    inrae_qc, polito_qc = compute_v2_grapevine_qc_mask()
    print("=== QC VIDEIRA (v2-rules) SOBRE ESTACOES DA v1 ===")
    print("INRAE reprovadas 2019-2024:")
    for (sid, yr), r in sorted(inrae_qc.items()):
        if not r["passed"]:
            print(f"  {sid} {yr}: {r['reasons']} (cov={r['coverage_frac']}, gap={r['max_gap_hours']}h)")
    print("Politecnico aprovadas:", [k for k, v in polito_qc.items() if v["passed"]])

    lwd_res = run_filtered_lwd_validation(inrae_qc, polito_qc)
    sr_res = run_filtered_semireal(inrae_qc)

    out = ROOT / "data" / "v2_v1_errata_audit.json"
    out.write_text(
        json.dumps(
            {
                "inrae_qc": {f"{k[0]}_{k[1]}": v for k, v in inrae_qc.items()},
                "polito_qc": polito_qc,
                "lwd_validation": lwd_res,
                "semireal": sr_res,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nAuditoria completa salva em {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
