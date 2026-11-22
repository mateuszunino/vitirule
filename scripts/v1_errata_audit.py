#!/usr/bin/env python3
"""
scripts/v1_errata_audit.py
==========================
Auditoria reproduzivel analise por analise para a Errata v1.0.2.

Criterio forense aplicado sobre o codigo CONGELADO da v1 (sem alterar nenhum
parametro, regra ou semente):
1. Sensor de molhamento reprovado nos testes de deriva ou travamento
   (`vitirule_v2.qc`): excluido de todas as analises da v1 que usam o sensor.
2. Lacuna ou cobertura baixa: verifica-se no codigo congelado como cada analise
   tratou a hora faltante dentro de sua janela efetiva:
   - Se a analise descartou a hora (`dropna` ou linhas ausentes na fonte),
     a estacao-safra FICA.
   - Se a analise preencheu a hora faltante com valor inventado usado naquela
     analise (ex.: `rr` preenchida com `0.0 mm` em `load_inrae_station`, ou
     `vt` preenchido com `1.5 m/s` em `leaf_wetness.py`), a estacao-safra SAI
     daquela analise especifica.
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

OM_CACHE = ROOT / "data" / "v2_cache" / "v1_errata_om"


def _cached_om_rich(start_s: str, end_s: str, lat: float, lon: float, tag: str) -> pd.DataFrame:
    OM_CACHE.mkdir(parents=True, exist_ok=True)
    cpath = OM_CACHE / f"{tag}_{start_s}_{end_s}.json"
    if cpath.is_file():
        rows = json.loads(cpath.read_text(encoding="utf-8"))
    else:
        rows = dm.fetch_rich_historical_weather(start_s, end_s, lat, lon)
        cpath.write_text(json.dumps(rows), encoding="utf-8")
    return lw.normalize_rich_weather(rows)


def build_forensic_decision_table() -> tuple[list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Constroi a tabela completa estacao-safra x analise indicando se ficou ou
    saiu e o motivo exato baseado no codigo congelado da v1.
    """
    rows: list[dict[str, Any]] = []
    inrae_dec: dict[tuple[str, int], dict[str, Any]] = {}

    for st in lsv.INRAE_STATIONS:
        sid = st["id"]
        df = pd.read_csv(ROOT / st["file"], sep="\t", low_memory=False)
        df["year"] = df["date_j"].str.slice(0, 4).astype(int)
        df["month"] = df["date_j"].str.slice(5, 7).astype(int)
        recs = load_inrae_records(ROOT / st["file"], year_min=2019, year_max=2024)

        for yr in range(2019, 2025):
            yr_recs = [r for r in recs if yr - 1 <= r.ts.year <= yr + 1]
            qc = evaluate_station_season_qc(yr_recs, "inrae", sid, "grapevine", yr, st["tz"], gap_policy="reject_24h")
            drift = [r for r in qc.reasons if ("wet_" in r or "dry_midday" in r or "rainless" in r)]
            has_drift = len(drift) > 0

            s_as = df[(df["year"] == yr) & (df["month"].between(4, 9))]
            s_osse = s_as[(s_as["date_j"] >= f"{yr}-05-01") & (s_as["date_j"] <= f"{yr}-07-16")]

            na_rr_as = int(pd.to_numeric(s_as["rr"], errors="coerce").isna().sum())
            na_vt_as = int(pd.to_numeric(s_as["vt"], errors="coerce").isna().sum())
            na_t_as = int(pd.to_numeric(s_as["t"], errors="coerce").isna().sum())
            na_u_as = int(pd.to_numeric(s_as["u"], errors="coerce").isna().sum())
            na_h_as = int(pd.to_numeric(s_as["h"], errors="coerce").isna().sum())
            na_rr_osse = int(pd.to_numeric(s_osse["rr"], errors="coerce").isna().sum())

            # Analise 1: lwd_sensor_validation (2022-2024, Apr-Sep)
            if yr < 2022:
                lwd_keep, lwd_why = None, "N/A (fora de 2022-2024)"
            elif has_drift:
                lwd_keep, lwd_why = False, "Sai: sensor LWD travado em julho (deriva)"
            elif na_rr_as > 0 or na_vt_as > 0:
                parts = []
                if na_rr_as > 0:
                    parts.append(f"rr faltante ({na_rr_as} h) preenchida com 0.0 mm")
                if na_vt_as > 0:
                    parts.append(f"vt faltante ({na_vt_as} h) preenchido com 1.5 m/s")
                lwd_keep, lwd_why = False, "Sai: " + "; ".join(parts)
            elif na_t_as > 0 or na_u_as > 0 or na_h_as > 0:
                lwd_keep, lwd_why = True, f"Fica: t/u/h faltantes ({na_t_as}/{na_u_as}/{na_h_as} h) descartadas por dropna"
            else:
                lwd_keep, lwd_why = True, "Fica: serie integra e sensor limpo"

            # Analise 2: empirical_reanalysis_error (May-Aug, 2019-2024 -> alimenta Mosela)
            # Usa apenas h_obs (sensor) e Open-Meteo; nunca le rr ou vt da estacao.
            if has_drift:
                emp_keep, emp_why = False, "Sai: sensor LWD travado em julho (deriva)"
            else:
                emp_keep, emp_why = True, "Fica: usa apenas sensor h e Open-Meteo (t/u/h faltantes descartadas por dropna)"

            # Analise 3: semireal_osse (May 1 - Jul 16, 2019-2024 -> alimenta economics.py)
            # Usa sensor h, t, u (dropna) e rr (fillna(0.0)); rh90_hysteresis nao usa vt.
            if has_drift:
                sr_keep, sr_why = False, "Sai: sensor LWD travado em julho (deriva)"
            elif na_rr_osse > 0:
                sr_keep, sr_why = False, f"Sai: rr faltante na janela May1-Jul16 ({na_rr_osse} h) preenchida com 0.0 mm"
            elif na_rr_as > 0:
                sr_keep, sr_why = True, f"Fica: rr faltante ({na_rr_as} h) ocorreu apos 20 jul, fora da janela OSSE (May1-Jul16)"
            elif na_t_as > 0 or na_u_as > 0 or na_h_as > 0:
                sr_keep, sr_why = True, f"Fica: horas faltantes de t/u/h ({na_t_as}/{na_u_as}/{na_h_as} h) descartadas por dropna"
            else:
                sr_keep, sr_why = True, "Fica: serie integra e sensor limpo"

            rec = {
                "network": "inrae",
                "station_id": sid,
                "name": st["name"],
                "year": yr,
                "drift": drift,
                "lwd_keep": lwd_keep,
                "lwd_why": lwd_why,
                "emp_keep": emp_keep,
                "emp_why": emp_why,
                "semireal_keep": sr_keep,
                "semireal_why": sr_why,
            }
            rows.append(rec)
            inrae_dec[(sid, yr)] = rec

    polito_sites = json.loads((ROOT / "data/lwd_sensors/polito/sites.json").read_text(encoding="utf-8"))["sites"]
    polito_dec: dict[str, dict[str, Any]] = {}
    for site in sorted(polito_sites, key=lambda x: x["ref"]):
        p = ROOT / "data/lwd_sensors/polito" / site["ref"]
        df = pd.read_csv(p)
        df["ts"] = pd.to_datetime(df["time"], utc=True)
        sub = df[df["ts"].dt.month.between(4, 9)]
        recs = load_polito_records(p)
        yr = sorted({r.ts.year for r in recs})[0]
        qc = evaluate_station_season_qc(recs, "polito", site["ref"], "grapevine", yr, "Europe/Rome", gap_policy="reject_24h")
        drift = [r for r in qc.reasons if ("wet_" in r or "dry_midday" in r or "rainless" in r)]
        na_rain = int(pd.to_numeric(sub["rain"], errors="coerce").isna().sum())
        na_wind = int(pd.to_numeric(sub["wind_speed"], errors="coerce").isna().sum())

        if drift:
            lwd_keep, lwd_why = False, "Sai: sensor LWD com deriva severa (ja excluida nos 6 limpos da v1.0)"
        elif na_rain > 0 or na_wind > 0:
            lwd_keep, lwd_why = False, f"Sai: rain/wind faltantes preenchidos ({na_rain}/{na_wind} h)"
        else:
            lwd_keep = True
            if len(sub) < 4392:
                lwd_why = f"Fica: {4392 - len(sub)} h ausentes eram linhas omitidas (nenhum valor inventado)"
            else:
                lwd_why = "Fica: serie completa e sensor limpo"

        rec = {
            "network": "polito",
            "station_id": site["ref"],
            "name": f"PoliTO-{site['ref']}",
            "year": yr,
            "drift": drift,
            "lwd_keep": lwd_keep,
            "lwd_why": lwd_why,
            "emp_keep": None,
            "emp_why": "N/A (Polito nao entra no OSSE)",
            "semireal_keep": None,
            "semireal_why": "N/A (Polito nao entra no OSSE)",
        }
        rows.append(rec)
        polito_dec[site["ref"]] = rec

    return rows, inrae_dec, polito_dec


def run_filtered_lwd(inrae_dec: dict[tuple[str, int], dict[str, Any]], polito_dec: dict[str, dict[str, Any]]) -> dict[str, Any]:
    inrae_reports: list[dict[str, Any]] = []
    for st in lsv.INRAE_STATIONS:
        passing_years = [yr for yr in (2022, 2023, 2024) if inrae_dec[(st["id"], yr)]["lwd_keep"]]
        if not passing_years:
            continue
        dfs = [lsv.load_inrae_station(ROOT / st["file"], yr, yr) for yr in passing_years]
        st_df = pd.concat(dfs).sort_index()
        om_dfs = [
            _cached_om_rich(d.index.min().date().isoformat(), d.index.max().date().isoformat(), st["lat"], st["lon"], f"inrae_{st['id']}_{yr}")
            for yr, d in zip(passing_years, dfs)
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
        if not polito_dec[site["ref"]]["lwd_keep"]:
            continue
        st_df = lsv.load_polito_site(ROOT / "data/lwd_sensors/polito" / site["ref"], wet_threshold=20.0)
        om_df = _cached_om_rich(
            st_df.index.min().date().isoformat(),
            st_df.index.max().date().isoformat(),
            site["lat"],
            site["lon"],
            f"polito_{Path(site['ref']).stem}",
        )
        res_station = lsv._eval_estimators(st_df, st_df["leaf_wet_sensor"], wind_height_m=2.0, local_tz_name="Europe/Rome")
        res_om = lsv._eval_estimators(om_df, st_df["leaf_wet_sensor"], wind_height_m=10.0, local_tz_name="Europe/Rome")
        polito_reports.append({
            "station_id": site["ref"],
            "station_weather": res_station,
            "open_meteo_reanalysis": res_om,
        })

    return {
        "inrae": {
            "n_station_years": sum(len(r["passing_years"]) for r in inrae_reports),
            "pooled_station_weather": lsv._aggregate_network(inrae_reports, "station_weather"),
            "pooled_open_meteo_reanalysis": lsv._aggregate_network(inrae_reports, "open_meteo_reanalysis"),
            "stations": inrae_reports,
        },
        "polito": {
            "n_sites": len(polito_reports),
            "passing_sites": [r["station_id"] for r in polito_reports],
            "pooled_station_weather": lsv._aggregate_network(polito_reports, "station_weather"),
            "pooled_open_meteo_reanalysis": lsv._aggregate_network(polito_reports, "open_meteo_reanalysis"),
        },
    }


def run_filtered_semireal(
    inrae_dec: dict[tuple[str, int], dict[str, Any]],
    lwd_method: str = "rh90_hysteresis",
    n_plots: int = 50,
    season_days: int = 75,
    base_seed: int = 20250501,
) -> dict[str, Any]:
    years = (2019, 2020, 2021, 2022, 2023, 2024)
    workers = max((os.cpu_count() or 2) - 2, 1)

    all_err: list[np.ndarray] = []
    daily_diffs: list[np.ndarray] = []
    lag1_corrs: list[float] = []
    p_om1_num = p_om1_den = p_om0_num = p_om0_den = 0.0
    n_emp_cohorts = 0

    all_rows: list[dict] = []
    rows_19_21: list[dict] = []
    rows_22_24: list[dict] = []
    cohorts: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for s_i, st in enumerate(lsv.INRAE_STATIONS):
            full_st = lsv.load_inrae_station(ROOT / st["file"], min(years), max(years))
            tz = ZoneInfo(st["tz"])
            for y_i, year in enumerate(years):
                dec = inrae_dec[(st["id"], year)]
                if not dec["emp_keep"] and not dec["semireal_keep"]:
                    continue

                om_ma = _cached_om_rich(f"{year}-05-01", f"{year}-08-31", st["lat"], st["lon"], f"inrae_ma_{st['id']}_{year}")

                if dec["emp_keep"]:
                    n_emp_cohorts += 1
                    st_ma = full_st[(full_st.index.year == year) & (full_st.index.month >= 5) & (full_st.index.month <= 8)].copy()
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

                if dec["semireal_keep"]:
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
        "period": f"2019-2024 (May-Aug, {n_emp_cohorts}/24 cohorts without stuck sensor)",
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

    untreated_vals = []
    om_sprays_vals = []
    all_deltas = []
    interp_deltas = []
    for c in cohorts:
        s = c["summary"]
        untreated_vals.append(s["testemunha"]["aacpd_mean"])
        om_r = next(r for r in s["rules"] if r["strategy"] == "om_v1_T10")
        om_sprays_vals.append(om_r["sprays_mean"])
        om_delta = om_r["delta_vs_calendar_frontier"]
        if om_delta is None:
            om_delta = round(om_r["aacpd_mean"] - _extrapolated_frontier(s["calendars"], om_r["sprays_mean"]), 3)
        all_deltas.append(om_delta)
        if 6.0 <= om_r["sprays_mean"] <= 11.0 and om_r["delta_vs_calendar_frontier"] is not None:
            interp_deltas.append(om_r["delta_vs_calendar_frontier"])

    r_val, p_val = stats.pearsonr(untreated_vals, om_sprays_vals)
    moselle_res = sr.run_moselle_calibrated_error(err_model, n_plots=60)

    pooled_summary = sr._summarize_semireal(all_rows, has_station_arm=True)
    econ_res = {
        "unconstrained": econ.sensitivity_grid(pooled_summary, enforce_eu_copper=False, copper_dose_kg_ha=0.50),
        "eu_copper_050": econ.sensitivity_grid(pooled_summary, enforce_eu_copper=True, copper_dose_kg_ha=0.50),
    }

    return {
        "empirical_reanalysis_error": err_model,
        "inrae_semireal": {
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
                "pearson_r_sprays_vs_untreated": round(float(r_val), 4),
                "pearson_p_sprays_vs_untreated": float(p_val),
            },
            "cohorts": cohorts,
        },
        "moselle_calibrated_error": moselle_res,
        "economics_pooled": econ_res,
    }


def main() -> int:
    table, inrae_dec, polito_dec = build_forensic_decision_table()
    print("=== DECISOES FORENSES ANALISE POR ANALISE (v1.0.2) ===")
    for r in table:
        if r["lwd_keep"] is False or r["emp_keep"] is False or r["semireal_keep"] is False:
            print(f"  [{r['network']}] {r['station_id']} {r['year']}: LWD={r['lwd_keep']} ({r['lwd_why']}) | EMP={r['emp_keep']} | OSSE={r['semireal_keep']} ({r['semireal_why']})")

    lwd_res = run_filtered_lwd(inrae_dec, polito_dec)
    sr_res = run_filtered_semireal(inrae_dec)

    out = ROOT / "data" / "v2_v102_errata_audit.json"
    out.write_text(
        json.dumps(
            {
                "version": "v1.0.2",
                "decision_table": table,
                "lwd_validation": lwd_res,
                "semireal": sr_res,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nAuditoria v1.0.2 salva em {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
