#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/generate_report_figures.py
==================================
Generates publication-ready, English-only vector SVG figures for
`docs/technical_report.md` directly from audited clean-sample outputs
(`data/v2_v102_errata_audit.json`) and reproduced sensor-driven timelines
(no rule or parameter changes):

  1. docs/figures/fig1_semireal_pareto.svg
     Sensor-driven INRAE Pareto frontier (2019-2024, N = 950)
     showing fixed calendars, pooled rule means, and all 19 clean
     station-year cohorts (marking interpolation [6-11] vs extrapolation).
  2. docs/figures/fig2_failure_timelines.svg
     Diagnostic daily timelines of Champagne 2022 and Champagne 2019:
     measured sensor LWD, Open-Meteo LWD, station rainfall, simulated daily
     SEIR new infections (S -> E1), mean severity trajectories, and
     spray dates of `om_v1_T10` vs. reference fixed calendars.
  3. docs/figures/fig3a_econ_unconstrained.svg
     docs/figures/fig3b_econ_eu_copper.svg
     English economic sensitivity maps (damage slope k vs. gross revenue)
     with clean, unclipped labels and legends.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import downy_mildew as dm
import epidemiology_assimilation as ea
import leaf_wetness as lw
import lwd_sensor_validation as lsv
import osse_benchmark as osse
import pareto_analysis as pa

FIG_DIR = ROOT / "docs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Figure 1: Sensor-Driven INRAE Pareto Frontier with 19 Clean Cohorts
# ---------------------------------------------------------------------------
def build_fig1_semireal_pareto() -> Path:
    raw = json.loads((ROOT / "data" / "v2_v102_errata_audit.json").read_text(encoding="utf-8"))
    sr = raw["semireal"]["inrae_semireal"]
    pooled = sr["pooled"]
    cohorts = sr["cohorts"]
    n_cohorts = len(cohorts)
    n_total = sr["total_plot_seasons"]

    cals = sorted(pooled["calendars"], key=lambda c: c["sprays_mean"])
    rules = {r["strategy"]: r for r in pooled["rules"]}

    W, H = 780, 445
    ml, mr, mt, mb = 72, 195, 44, 56
    pw, ph = W - ml - mr, H - mt - mb

    xmin, xmax = 1.8, 12.5
    ymin, ymax = 0.0, 260.0

    def sx(v: float) -> float:
        return ml + (v - xmin) / (xmax - xmin) * pw

    def sy(v: float) -> float:
        return mt + ph - (v - ymin) / (ymax - ymin) * ph

    reg_colors = {
        "Bordeaux": "#2563eb",
        "Alsace": "#059669",
        "Champagne": "#d97706",
        "Bourgogne": "#7c3aed",
    }
    reg_counts: dict[str, int] = {}
    for c in cohorts:
        reg_short = c["name"].split(" ")[0]
        reg_counts[reg_short] = reg_counts.get(reg_short, 0) + 1

    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="font-family:Segoe UI,Arial,sans-serif;background:#ffffff">',
        # Extrapolation shaded bands (<6 and >11 sprays)
        f'<rect x="{sx(xmin):.1f}" y="{mt}" width="{sx(6.0)-sx(xmin):.1f}" height="{ph}" fill="#f3f4f6"/>',
        f'<rect x="{sx(11.0):.1f}" y="{mt}" width="{sx(xmax)-sx(11.0):.1f}" height="{ph}" fill="#f3f4f6"/>',
        f'<line x1="{sx(6.0):.1f}" y1="{mt}" x2="{sx(6.0):.1f}" y2="{mt+ph}" stroke="#d1d5db" stroke-dasharray="4,3"/>',
        f'<line x1="{sx(11.0):.1f}" y1="{mt}" x2="{sx(11.0):.1f}" y2="{mt+ph}" stroke="#d1d5db" stroke-dasharray="4,3"/>',
        f'<text x="{(sx(xmin)+sx(6.0))/2:.1f}" y="{mt+15}" text-anchor="middle" font-size="9.5" fill="#6b7280">Extrapolation (&lt;6 sprays)</text>',
        f'<text x="{(sx(6.0)+sx(11.0))/2:.1f}" y="{mt+15}" text-anchor="middle" font-size="9.5" fill="#4b5563">Fixed-calendar range (6–11 sprays)</text>',
        # Title & axes labels
        f'<text x="{ml+pw/2:.1f}" y="25" text-anchor="middle" font-size="13.5" font-weight="600" fill="#0f172a">Sensor-Driven INRAE OSSE (2019–2024, N = {n_total}; {n_cohorts} Cohorts)</text>',
        f'<text x="{ml+pw/2:.1f}" y="{H-14}" text-anchor="middle" font-size="11.5" fill="#1f2937">Mean fungicide applications per season</text>',
        f'<text x="20" y="{mt+ph/2:.1f}" text-anchor="middle" font-size="11.5" fill="#1f2937" transform="rotate(-90 20 {mt+ph/2:.1f})">Mean foliar AUDPC (% × day)</text>',
    ]

    # Grid & ticks
    for yv in range(0, 261, 50):
        yy = sy(yv)
        elems.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" stroke="#e5e7eb" stroke-width="0.8"/>')
        elems.append(f'<text x="{ml-8}" y="{yy+3.5:.1f}" text-anchor="end" font-size="9.5" fill="#4b5563">{yv}</text>')
    for xv in range(2, 13):
        xx = sx(xv)
        elems.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{mt+ph}" stroke="#f1f5f9" stroke-width="0.8"/>')
        elems.append(f'<text x="{xx:.1f}" y="{mt+ph+16}" text-anchor="middle" font-size="9.5" fill="#4b5563">{xv}</text>')

    # Plot frame
    elems.append(f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="none" stroke="#9ca3af" stroke-width="1"/>')

    # 19 individual cohorts for om_v1_T10
    for c in cohorts:
        r = {x["strategy"]: x for x in c["summary"]["rules"]}["om_v1_T10"]
        reg_short = c["name"].split(" ")[0]
        col = reg_colors.get(reg_short, "#64748b")
        cx, cy = sx(r["sprays_mean"]), sy(r["aacpd_mean"])
        is_fail = (reg_short == "Champagne" and c["year"] in (2022, 2019))
        if is_fail:
            elems.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.2" fill="#dc2626" fill-opacity="0.88" stroke="#7f1d1d" stroke-width="1.3"/>')
            lbl = f"{reg_short} {c['year']} ({r['sprays_mean']:.1f}, {r['aacpd_mean']:.0f})"
            if c["year"] == 2022:
                lx_off, ly_off, anchor = cx + 8, cy + 3.5, "start"
            else:
                lx_off, ly_off, anchor = cx - 8, cy + 16.0, "end"
                elems.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx_off+2:.1f}" y2="{ly_off-3:.1f}" stroke="#b91c1c" stroke-width="0.7" opacity="0.7"/>')
            elems.append(f'<text x="{lx_off:.1f}" y="{ly_off:.1f}" text-anchor="{anchor}" font-size="9.5" font-weight="600" fill="#b91c1c">{lbl}</text>')
        else:
            elems.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.8" fill="{col}" fill-opacity="0.45" stroke="{col}" stroke-width="1"/>')

    # Pooled fixed calendar frontier
    cal_pts = " ".join(f"{sx(c['sprays_mean']):.1f},{sy(c['aacpd_mean']):.1f}" for c in cals)
    elems.append(f'<polyline points="{cal_pts}" fill="none" stroke="#111827" stroke-width="2.4"/>')
    cal_label_offsets = {"cal_14d": (-4, -10), "cal_12d": (4, -10), "cal_10d": (6, -9), "cal_7d": (0, -10)}
    for c in cals:
        cx, cy = sx(c["sprays_mean"]), sy(c["aacpd_mean"])
        dx, dy = cal_label_offsets.get(c["strategy"], (0, -9))
        elems.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="#111827" stroke="#ffffff" stroke-width="1"/>')
        lbl = c["strategy"].replace("cal_", "")
        elems.append(f'<text x="{cx+dx:.1f}" y="{cy+dy:.1f}" text-anchor="middle" font-size="9.5" font-weight="600" fill="#111827">{lbl}</text>')

    # Pooled rules with 95% CI error bars
    pooled_specs = [
        ("om_v1_T10", "#059669", "diamond", "om_v1_T10 (pooled)"),
        ("om_v2_T10", "#d97706", "square", "om_v2_T10 (pooled)"),
        ("st_v1_T10", "#0284c7", "triangle", "st_v1_T10 (pooled)"),
    ]
    for key, col, shape, _ in pooled_specs:
        r = rules[key]
        cx, cy = sx(r["sprays_mean"]), sy(r["aacpd_mean"])
        lo, hi = sy(r["aacpd_ci95"][0]), sy(r["aacpd_ci95"][1])
        elems.append(f'<line x1="{cx:.1f}" y1="{lo:.1f}" x2="{cx:.1f}" y2="{hi:.1f}" stroke="{col}" stroke-width="1.6"/>')
        if shape == "diamond":
            pts = f"{cx:.1f},{cy-6.5:.1f} {cx+6.5:.1f},{cy:.1f} {cx:.1f},{cy+6.5:.1f} {cx-6.5:.1f},{cy:.1f}"
            elems.append(f'<polygon points="{pts}" fill="{col}" stroke="#ffffff" stroke-width="1.1"/>')
        elif shape == "square":
            elems.append(f'<rect x="{cx-5:.1f}" y="{cy-5:.1f}" width="10" height="10" fill="{col}" stroke="#ffffff" stroke-width="1.1"/>')
        else:
            pts = f"{cx:.1f},{cy-6:.1f} {cx+6:.1f},{cy+5:.1f} {cx-6:.1f},{cy+5:.1f}"
            elems.append(f'<polygon points="{pts}" fill="{col}" stroke="#ffffff" stroke-width="1.1"/>')

    # Zoom callout annotations for pooled points
    r_v1 = rules["om_v1_T10"]
    delta_v1 = r_v1["delta_vs_calendar_frontier"]
    elems.append(f'<text x="{sx(r_v1["sprays_mean"])+10:.1f}" y="{sy(r_v1["aacpd_mean"])+26:.1f}" font-size="9.2" font-weight="600" fill="#047857">om_v1: {delta_v1:+.1f} vs. frontier</text>')

    # Legend (right panel, plenty of room, zero clipping)
    lx, ly = ml + pw + 14, mt + 6
    elems.append(f'<rect x="{lx-6}" y="{ly-6}" width="182" height="278" rx="4" fill="#fafafa" stroke="#e5e7eb"/>')
    elems.append(f'<text x="{lx}" y="{ly+10}" font-size="10.5" font-weight="700" fill="#0f172a">Pooled Means (N = {n_total})</text>')

    # Calendar line legend
    yy = ly + 28
    elems.append(f'<line x1="{lx}" y1="{yy-3}" x2="{lx+18}" y2="{yy-3}" stroke="#111827" stroke-width="2.4"/>')
    elems.append(f'<circle cx="{lx+9}" cy="{yy-3}" r="3.5" fill="#111827"/>')
    elems.append(f'<text x="{lx+24}" y="{yy}" font-size="9.5" fill="#1f2937">Fixed calendars (6–11 sp)</text>')

    for idx, (key, col, shape, lbl) in enumerate(pooled_specs):
        yy = ly + 48 + idx * 20
        cx, cy = lx + 9, yy - 3
        if shape == "diamond":
            pts = f"{cx},{cy-5} {cx+5},{cy} {cx},{cy+5} {cx-5},{cy}"
            elems.append(f'<polygon points="{pts}" fill="{col}"/>')
        elif shape == "square":
            elems.append(f'<rect x="{cx-4.5}" y="{cy-4.5}" width="9" height="9" fill="{col}"/>')
        else:
            pts = f"{cx},{cy-5} {cx+5},{cy+4} {cx-5},{cy+4}"
            elems.append(f'<polygon points="{pts}" fill="{col}"/>')
        r = rules[key]
        elems.append(f'<text x="{lx+24}" y="{yy}" font-size="9.3" fill="#1f2937">{key} ({r["sprays_mean"]:.2f}, {r["aacpd_mean"]:.1f})</text>')

    yy = ly + 122
    elems.append(f'<line x1="{lx}" y1="{yy-10}" x2="{lx+170}" y2="{yy-10}" stroke="#e5e7eb"/>')
    elems.append(f'<text x="{lx}" y="{yy+4}" font-size="10.5" font-weight="700" fill="#0f172a">{n_cohorts} Cohorts (om_v1_T10)</text>')
    for idx, (reg, col) in enumerate(reg_colors.items()):
        ry = yy + 22 + idx * 18
        elems.append(f'<circle cx="{lx+9}" cy="{ry-3}" r="3.8" fill="{col}" fill-opacity="0.55" stroke="{col}"/>')
        elems.append(f'<text x="{lx+24}" y="{ry}" font-size="9.3" fill="#374151">{reg} ({reg_counts.get(reg, 0)} yrs)</text>')
    ry = yy + 22 + 4 * 18 + 2
    elems.append(f'<circle cx="{lx+9}" cy="{ry-3}" r="4.6" fill="#dc2626" stroke="#7f1d1d"/>')
    elems.append(f'<text x="{lx+24}" y="{ry}" font-size="9.3" font-weight="600" fill="#b91c1c">Worst tail-risk cohorts</text>')

    elems.append("</svg>")
    out = FIG_DIR / "fig1_semireal_pareto.svg"
    out.write_text("\n".join(elems), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Figure 2: Diagnostic Timelines for Champagne 2022 & Bordeaux 2021
# ---------------------------------------------------------------------------
def _simulate_seir_with_new_inf(
    wdf: pd.DataFrame,
    plot: osse.SeirPlotParams,
    spray_times_utc: list[datetime],
    true_wet: np.ndarray,
    infectious_days: float = 12.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact copy of osse.simulate_seir_trajectory returning (visible_pct, hourly_new_inf_pct)."""
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
    new_inf_pct = np.zeros(n, dtype=float)
    active_spray_idx = 0
    rain_since_spray = 0.0
    last_spray_epoch = None

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
        new_inf = min(max(plot.beta_max * g_inf[h] * wet_factor * (1.0 - protection) * S * inoculum, 0.0), S)
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
        new_inf_pct[h] = 100.0 * new_inf

    return visible_pct, new_inf_pct


def _timeline_plot_worker(task: dict) -> dict:
    truth_wdf = task["truth_wdf"]
    true_wet = task["true_wet"]
    om_aligned = task["om_aligned"]
    om_daily_full = task["om_daily_full"]
    plot = task["plot"]
    season_start = task["season_start"]
    season_days = task["season_days"]
    eval_ts_list = task["eval_ts_list"]
    eval_indices = task["eval_indices"]
    daily_indices = task["daily_indices"]
    local_tz_name = task["local_tz_name"]
    ref_cal_interval = task["ref_cal_interval"]
    seed = task["seed"]

    tz = ZoneInfo(local_tz_name)
    rng = np.random.default_rng(seed)
    v1_cfg = osse.VineyardDecisionConfig(lwd_method="rh90_hysteresis")

    sprays: list[datetime] = []
    spray_offsets: list[int] = []
    for k, eval_ts in enumerate(eval_ts_list):
        eval_pd = pd.Timestamp(eval_ts)
        fc_end_pd = eval_pd + pd.Timedelta(hours=168)
        eval_day = eval_ts.astimezone(tz).date()
        obs_d = om_daily_full[om_daily_full["day"] <= eval_day]
        fc_om_raw = osse._perturb_forecast(om_aligned[(om_aligned.index > eval_pd) & (om_aligned.index <= fc_end_pd)], rng)
        fc_d = dm.compute_downy_mildew_daily(fc_om_raw, lwd_method="rh90_hysteresis", local_tz_name=local_tz_name)
        rain_since = 0.0
        if sprays:
            rain_since = float(
                om_aligned[(om_aligned.index > pd.Timestamp(sprays[-1])) & (om_aligned.index <= eval_pd)]["precip_mm"]
                .fillna(0.0).sum()
            )
        if osse.decide_climate_forecast_washoff(obs_d, fc_d, sprays[-1] if sprays else None, eval_ts, v1_cfg, pa.FROZEN_OPERATING_THRESHOLD, rain_since):
            sprays.append(eval_ts + timedelta(hours=2))
            spray_offsets.append(k * 3)

    cal_sprays = [season_start + timedelta(days=d, hours=2) for d in range(0, season_days, ref_cal_interval)]
    sev_om, inf_om = _simulate_seir_with_new_inf(truth_wdf, plot, sprays, true_wet)
    sev_cal, inf_cal = _simulate_seir_with_new_inf(truth_wdf, plot, cal_sprays, true_wet)
    sev_test, inf_test = _simulate_seir_with_new_inf(truth_wdf, plot, [], true_wet)

    # Aggregate hourly new_inf into daily buckets aligned to day 0..75
    n_days = len(daily_indices) - 1
    d_inf_om = [float(inf_om[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(n_days)]
    d_inf_cal = [float(inf_cal[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(n_days)]
    d_sev_om = [float(sev_om[daily_indices[d]]) for d in range(n_days + 1)]
    d_sev_cal = [float(sev_cal[daily_indices[d]]) for d in range(n_days + 1)]
    d_sev_test = [float(sev_test[daily_indices[d]]) for d in range(n_days + 1)]

    om_aacpd = ea.aacpd(eval_ts_list, [float(sev_om[idx]) for idx in eval_indices])
    cal_aacpd = ea.aacpd(eval_ts_list, [float(sev_cal[idx]) for idx in eval_indices])
    return {
        "spray_offsets": spray_offsets,
        "n_sprays": len(sprays),
        "om_aacpd": om_aacpd,
        "cal_aacpd": cal_aacpd,
        "d_inf_om": d_inf_om,
        "d_inf_cal": d_inf_cal,
        "d_sev_om": d_sev_om,
        "d_sev_cal": d_sev_cal,
        "d_sev_test": d_sev_test,
    }


def _extract_cohort_timeline(station_prefix: str, year: int, ref_cal_interval: int) -> dict[str, Any]:
    years = (2019, 2020, 2021, 2022, 2023, 2024)
    base_seed = 20250501
    s_i, st = next((i, s) for i, s in enumerate(lsv.INRAE_STATIONS) if s["name"].startswith(station_prefix))
    y_i = years.index(year)

    full_st = lsv.load_inrae_station(st["file"], min(years), max(years))
    tz = ZoneInfo(st["tz"])
    start_utc = pd.Timestamp(f"{year}-05-01T00:00:00Z")
    end_utc = pd.Timestamp(f"{year}-08-05T23:00:00Z")
    st_sub = full_st[(full_st.index >= start_utc) & (full_st.index <= end_utc)].copy()
    om_rows = dm.fetch_rich_historical_weather(f"{year}-05-01", f"{year}-08-05", st["lat"], st["lon"])
    om_wdf = lw.normalize_rich_weather(om_rows)
    common = st_sub.index.intersection(om_wdf.index)

    truth_wdf = st_sub.loc[common, ["temp_c", "rh_pct", "precip_mm", "wind_ms", "rad_wm2"]].copy()
    truth_wdf["dewpoint_c"] = lw.magnus_dewpoint_c(truth_wdf["temp_c"].to_numpy(), truth_wdf["rh_pct"].to_numpy())
    true_wet = np.clip(st_sub.loc[common, "sensor_hours"].to_numpy(dtype=float), 0.0, 1.0)
    om_aligned = om_wdf.loc[common].copy()
    om_daily_full = dm.compute_downy_mildew_daily(om_aligned, lwd_method="rh90_hysteresis", local_tz_name=st["tz"])
    om_wet = lw.estimate_leaf_wetness(om_aligned, method="rh90_hysteresis", wind_height_m=10.0).to_numpy(dtype=float)

    t_min = common.min()
    start_local = t_min.tz_convert(tz).normalize() + pd.Timedelta(hours=9)
    if start_local.tz_convert("UTC") < t_min:
        start_local += pd.Timedelta(days=1)
    season_start = start_local.tz_convert("UTC").to_pydatetime()
    season_days = 75
    eval_ts_list = [season_start + timedelta(days=d) for d in range(0, season_days + 1, 3)]
    common_ep = ea._epoch_seconds(common)
    eval_indices = [int(np.argmin(np.abs(common_ep - ea._epoch_seconds([ts])[0]))) for ts in eval_ts_list]
    day_ts_list = [season_start + timedelta(days=d) for d in range(0, season_days + 1)]
    daily_indices = [int(np.argmin(np.abs(common_ep - ea._epoch_seconds([ts])[0]))) for ts in day_ts_list]

    c_seed = base_seed + s_i * 100_000 + y_i * 10_000
    plots = osse._build_seir_plots(n_plots=50, seed=c_seed)
    tasks = [
        {
            "truth_wdf": truth_wdf,
            "true_wet": true_wet,
            "om_aligned": om_aligned,
            "om_daily_full": om_daily_full,
            "plot": p,
            "season_start": season_start,
            "season_days": season_days,
            "eval_ts_list": eval_ts_list,
            "eval_indices": eval_indices,
            "daily_indices": daily_indices,
            "local_tz_name": st["tz"],
            "ref_cal_interval": ref_cal_interval,
            "seed": c_seed + i * 131,
        }
        for i, p in enumerate(plots)
    ]
    workers = max((os.cpu_count() or 2) - 2, 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        res = list(pool.map(_timeline_plot_worker, tasks))

    spray_freq = {}
    for r in res:
        for d_off in r["spray_offsets"]:
            spray_freq[d_off] = spray_freq.get(d_off, 0) + 1

    # Daily meteorological arrays (days 0..74)
    st_rain = truth_wdf["precip_mm"].fillna(0.0).to_numpy(dtype=float)
    om_rain = om_aligned["precip_mm"].fillna(0.0).to_numpy(dtype=float)
    d_sens_lwd = [float(true_wet[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(season_days)]
    d_om_lwd = [float(om_wet[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(season_days)]
    d_st_rain = [float(st_rain[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(season_days)]
    d_om_rain = [float(om_rain[daily_indices[d]:daily_indices[d + 1]].sum()) for d in range(season_days)]

    # Daily OM secondary_sv score
    sv_map = dict(zip(om_daily_full["day"], om_daily_full["secondary_sv"]))
    d_dates = [(season_start + timedelta(days=d)).astimezone(tz).date().isoformat() for d in range(season_days + 1)]
    d_om_sv = [int(sv_map.get((season_start + timedelta(days=d)).astimezone(tz).date(), 0)) for d in range(season_days)]

    cal_days = list(range(0, season_days, ref_cal_interval))
    return {
        "station": st["name"],
        "year": year,
        "ref_cal_interval": ref_cal_interval,
        "ref_cal_days": cal_days,
        "om_sprays_mean": round(float(np.mean([r["n_sprays"] for r in res])), 2),
        "om_aacpd_mean": round(float(np.mean([r["om_aacpd"] for r in res])), 2),
        "cal_aacpd_mean": round(float(np.mean([r["cal_aacpd"] for r in res])), 2),
        "spray_freq_pct": {str(k): round(100.0 * v / len(res), 1) for k, v in sorted(spray_freq.items())},
        "dates": d_dates,
        "sensor_lwd_h": [round(x, 2) for x in d_sens_lwd],
        "om_lwd_h": [round(x, 2) for x in d_om_lwd],
        "station_rain_mm": [round(x, 2) for x in d_st_rain],
        "om_rain_mm": [round(x, 2) for x in d_om_rain],
        "om_sv": d_om_sv,
        "mean_new_inf_om_pct": [round(float(x), 4) for x in np.mean([r["d_inf_om"] for r in res], axis=0)],
        "mean_new_inf_cal_pct": [round(float(x), 4) for x in np.mean([r["d_inf_cal"] for r in res], axis=0)],
        "mean_sev_om_pct": [round(float(x), 3) for x in np.mean([r["d_sev_om"] for r in res], axis=0)],
        "mean_sev_cal_pct": [round(float(x), 3) for x in np.mean([r["d_sev_cal"] for r in res], axis=0)],
        "mean_sev_test_pct": [round(float(x), 3) for x in np.mean([r["d_sev_test"] for r in res], axis=0)],
    }


def build_fig2_failure_timelines(recompute: bool = False) -> tuple[Path, dict]:
    summary_path = FIG_DIR / "failure_timelines_summary.json"
    if not recompute and summary_path.is_file():
        cached = json.loads(summary_path.read_text(encoding="utf-8"))
        if "champagne_2022" in cached and "champagne_2019" in cached:
            ch22, ch19 = cached["champagne_2022"], cached["champagne_2019"]
        else:
            recompute = True
    if recompute or not summary_path.is_file():
        ch22 = _extract_cohort_timeline("Champagne", 2022, ref_cal_interval=14)
        ch19 = _extract_cohort_timeline("Champagne", 2019, ref_cal_interval=14)
        summary_path.write_text(json.dumps({"champagne_2022": ch22, "champagne_2019": ch19}, indent=2), encoding="utf-8")

    W, H = 780, 658
    ml, mr = 64, 58
    pw = W - ml - mr
    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="font-family:Segoe UI,Arial,sans-serif;background:#ffffff">',
        f'<text x="{W/2:.1f}" y="22" text-anchor="middle" font-size="13.5" font-weight="700" fill="#0f172a">Daily Diagnostic Timelines of Tail-Risk Failure Cohorts (Measured INRAE Sensor Truth)</text>',
    ]

    panels = [
        (
            f"A. Champagne (Fagnières, 2022): om_v1_T10 ({ch22['om_sprays_mean']:.1f} sp, AUDPC {ch22['om_aacpd_mean']:.1f}) vs. cal_14d (6.0 sp, AUDPC {ch22['cal_aacpd_mean']:.1f})",
            ch22,
            40,
        ),
        (
            f"B. Champagne (Fagnières, 2019): om_v1_T10 ({ch19['om_sprays_mean']:.2f} sp, AUDPC {ch19['om_aacpd_mean']:.1f}) vs. cal_14d (6.0 sp, AUDPC {ch19['cal_aacpd_mean']:.1f})",
            ch19,
            332,
        ),
    ]

    tick_days = [(0, "May 1"), (14, "May 15"), (31, "Jun 1"), (45, "Jun 15"), (61, "Jul 1"), (75, "Jul 15")]

    for title, data, top_y in panels:
        elems.append(f'<text x="{ml}" y="{top_y+12}" font-size="11.2" font-weight="700" fill="#1e293b">{title}</text>')

        # Top sub-track: LWD (h/day, 0-24) and Rain (mm/day, right axis 0-40)
        t1_y, t1_h = top_y + 22, 82
        # Bottom sub-track: Severity (%, left axis) + Daily New Infections (%, right axis) + Spray markers
        t2_y, t2_h = top_y + 114, 132

        def sx(d: float) -> float:
            return ml + (d / 75.0) * pw

        # --- Sub-track 1: Sensor LWD bars, OM LWD line, station rain ---
        elems.append(f'<rect x="{ml}" y="{t1_y}" width="{pw}" height="{t1_h}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.9"/>')
        for lv in (0, 12, 24):
            yy = t1_y + t1_h - (lv / 24.0) * t1_h
            elems.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" stroke="#e2e8f0" stroke-width="0.7"/>')
            elems.append(f'<text x="{ml-6}" y="{yy+3:.1f}" text-anchor="end" font-size="8.5" fill="#475569">{lv}h</text>')
        rain_max = max(30.0, float(max(data["station_rain_mm"])) * 1.1)
        for rv in (0, round(rain_max / 2), round(rain_max)):
            yy = t1_y + t1_h - (rv / rain_max) * t1_h
            elems.append(f'<text x="{ml+pw+6}" y="{yy+3:.1f}" text-anchor="start" font-size="8.5" fill="#1d4ed8">{rv}mm</text>')
        elems.append(f'<text x="16" y="{t1_y+t1_h/2:.1f}" text-anchor="middle" font-size="8.8" fill="#0369a1" transform="rotate(-90 16 {t1_y+t1_h/2:.1f})">LWD (h/d)</text>')
        elems.append(f'<text x="{W-12}" y="{t1_y+t1_h/2:.1f}" text-anchor="middle" font-size="8.8" fill="#1d4ed8" transform="rotate(90 {W-12} {t1_y+t1_h/2:.1f})">Rain (mm)</text>')

        bw = max(pw / 75.0 - 1.2, 3.0)
        om_pts = []
        for d in range(75):
            x = sx(d)
            sh = (min(data["sensor_lwd_h"][d], 24.0) / 24.0) * t1_h
            elems.append(f'<rect x="{x:.1f}" y="{t1_y+t1_h-sh:.1f}" width="{bw:.1f}" height="{sh:.1f}" fill="#7dd3fc" fill-opacity="0.75"/>')
            rn = data["station_rain_mm"][d]
            if rn > 0.2:
                rh = (min(rn, rain_max) / rain_max) * t1_h
                elems.append(f'<rect x="{x+bw*0.35:.1f}" y="{t1_y+t1_h-rh:.1f}" width="{bw*0.45:.1f}" height="{rh:.1f}" fill="#1d4ed8" fill-opacity="0.80"/>')
            oy = t1_y + t1_h - (min(data["om_lwd_h"][d], 24.0) / 24.0) * t1_h
            om_pts.append(f"{x+bw/2:.1f},{oy:.1f}")
        elems.append(f'<polyline points="{" ".join(om_pts)}" fill="none" stroke="#0f766e" stroke-width="1.3" stroke-dasharray="3,2"/>')

        # --- Sub-track 2: Daily new infections, Severity curves, Spray ticks ---
        elems.append(f'<rect x="{ml}" y="{t2_y}" width="{pw}" height="{t2_h}" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.9"/>')
        sev_max = max(20.0, float(np.ceil(max(data["mean_sev_test_pct"]) / 10.0) * 10.0))
        inf_max = max(0.5, float(max(data["mean_new_inf_om_pct"])) * 1.35)

        for sv in np.linspace(0, sev_max, 5):
            yy = t2_y + t2_h - (sv / sev_max) * t2_h
            elems.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" stroke="#f1f5f9" stroke-width="0.8"/>')
            elems.append(f'<text x="{ml-6}" y="{yy+3:.1f}" text-anchor="end" font-size="8.5" fill="#475569">{sv:.0f}%</text>')
        for iv in (0.0, inf_max * 0.5, inf_max):
            yy = t2_y + t2_h - (iv / inf_max) * t2_h
            elems.append(f'<text x="{ml+pw+6}" y="{yy+3:.1f}" text-anchor="start" font-size="8.5" fill="#ea580c">{iv:.1f}%</text>')
        elems.append(f'<text x="16" y="{t2_y+t2_h/2:.1f}" text-anchor="middle" font-size="8.8" fill="#1f2937" transform="rotate(-90 16 {t2_y+t2_h/2:.1f})">Severity (%)</text>')
        elems.append(f'<text x="{W-12}" y="{t2_y+t2_h/2:.1f}" text-anchor="middle" font-size="8.8" fill="#ea580c" transform="rotate(90 {W-12} {t2_y+t2_h/2:.1f})">New inf. (%/d)</text>')

        # Daily new infections under om_v1_T10 (orange bars)
        for d in range(75):
            val = data["mean_new_inf_om_pct"][d]
            if val > 0.005:
                ih = (min(val, inf_max) / inf_max) * t2_h
                elems.append(f'<rect x="{sx(d):.1f}" y="{t2_y+t2_h-ih:.1f}" width="{bw:.1f}" height="{ih:.1f}" fill="#fb923c" fill-opacity="0.55"/>')

        # Severity curves
        def _poly(arr, stroke, width, dash=""):
            pts = " ".join(f"{sx(d):.1f},{t2_y + t2_h - (min(arr[d], sev_max)/sev_max)*t2_h:.1f}" for d in range(len(arr)))
            ds = f' stroke-dasharray="{dash}"' if dash else ""
            return f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width}"{ds}/>'

        elems.append(_poly(data["mean_sev_test_pct"], "#94a3b8", "1.6", "4,3"))
        elems.append(_poly(data["mean_sev_cal_pct"], "#1e3a8a", "2.1"))
        elems.append(_poly(data["mean_sev_om_pct"], "#dc2626", "2.2"))

        # Spray markers along top strip of sub-track 2
        # Fixed calendar: navy dots at t2_y + 7
        for cd in data["ref_cal_days"]:
            cx = sx(cd)
            elems.append(f'<circle cx="{cx:.1f}" cy="{t2_y+8}" r="3.4" fill="#1e3a8a" stroke="#ffffff" stroke-width="0.7"/>')
            elems.append(f'<line x1="{cx:.1f}" y1="{t2_y+12}" x2="{cx:.1f}" y2="{t2_y+t2_h}" stroke="#1e3a8a" stroke-opacity="0.14" stroke-dasharray="2,2"/>')
        # om_v1_T10 sprays: green downward triangles scaled/opacity by frequency across 50 plots (only >=10%)
        for d_str, pct in data["spray_freq_pct"].items():
            if pct < 10.0:
                continue
            d_off = int(d_str)
            cx = sx(d_off)
            op = 0.35 + 0.65 * (pct / 100.0)
            pts = f"{cx-4.2:.1f},{t2_y+16} {cx+4.2:.1f},{t2_y+16} {cx:.1f},{t2_y+24}"
            elems.append(f'<polygon points="{pts}" fill="#059669" fill-opacity="{op:.2f}" stroke="#065f46" stroke-width="0.7"/>')
            if pct >= 40.0:
                elems.append(f'<line x1="{cx:.1f}" y1="{t2_y+24}" x2="{cx:.1f}" y2="{t2_y+t2_h}" stroke="#059669" stroke-opacity="0.22"/>')

        # Date x-axis ticks
        for d_off, lbl in tick_days:
            xx = sx(d_off)
            elems.append(f'<line x1="{xx:.1f}" y1="{t2_y+t2_h}" x2="{xx:.1f}" y2="{t2_y+t2_h+4}" stroke="#475569"/>')
            elems.append(f'<text x="{xx:.1f}" y="{t2_y+t2_h+15}" text-anchor="middle" font-size="9" fill="#334155">{lbl}</text>')

    # Shared clean 2-row horizontal legend well below Panel B date labels
    row1 = [
        ("rect", "#7dd3fc", "Sensor LWD (h/day)"),
        ("dash", "#0f766e", "Open-Meteo LWD (h/day)"),
        ("rect", "#1d4ed8", "Station rainfall (mm)"),
        ("rect", "#fb923c", "Daily new SEIR inf. (om_v1)"),
    ]
    row2 = [
        ("line", "#dc2626", "Severity: om_v1_T10"),
        ("line", "#1e3a8a", "Severity: ref. calendar"),
        ("dash", "#94a3b8", "Untreated"),
        ("tri", "#059669", "om_v1 spray (>=10% plots)"),
        ("dot", "#1e3a8a", "Calendar spray"),
    ]
    elems.append(f'<rect x="{ml}" y="608" width="{pw}" height="42" rx="4" fill="#f8fafc" stroke="#e2e8f0"/>')
    for row_items, ly in ((row1, 624), (row2, 642)):
        cx = ml + 12
        for kind, col, txt in row_items:
            if kind == "rect":
                elems.append(f'<rect x="{cx}" y="{ly-8}" width="10" height="8" fill="{col}"/>')
            elif kind == "line":
                elems.append(f'<line x1="{cx}" y1="{ly-4}" x2="{cx+12}" y2="{ly-4}" stroke="{col}" stroke-width="2.2"/>')
            elif kind == "dash":
                elems.append(f'<line x1="{cx}" y1="{ly-4}" x2="{cx+12}" y2="{ly-4}" stroke="{col}" stroke-width="1.6" stroke-dasharray="3,2"/>')
            elif kind == "tri":
                elems.append(f'<polygon points="{cx},{ly-8} {cx+9},{ly-8} {cx+4.5},{ly-1}" fill="{col}"/>')
            elif kind == "dot":
                elems.append(f'<circle cx="{cx+5}" cy="{ly-4}" r="3.4" fill="{col}"/>')
            elems.append(f'<text x="{cx+15}" y="{ly-1}" font-size="8.8" fill="#1f2937">{txt}</text>')
            cx += 26 + len(txt) * 5.05

    elems.append("</svg>")
    out = FIG_DIR / "fig2_failure_timelines.svg"
    out.write_text("\n".join(elems), encoding="utf-8")
    return out, {"champagne_2022": ch22, "champagne_2019": ch19}


# ---------------------------------------------------------------------------
# Figure 3a & 3b: English Economic Sensitivity Maps (zero clipping)
# ---------------------------------------------------------------------------
def _write_english_econ_svg(sens: dict, title: str, subtitle: str, out_path: Path) -> Path:
    slopes = sens["slopes"]
    revs = sens["revenues_eur_ha"]
    grid = sens["grid_revenues_by_slopes"]

    palette = {
        "cal_7d": "#1f2937",
        "cal_10d": "#6b7280",
        "cal_12d": "#9ca3af",
        "cal_14d": "#d1d5db",
        "om_v1_T10": "#059669",
        "st_v1_T10": "#0284c7",
        "om_v2_T10": "#d97706",
        "st_v2_T10": "#7c3aed",
        "testemunha": "#dc2626",
    }
    labels = {
        "testemunha": "untreated",
        "cal_7d": "cal_7d (11.0 sp)",
        "cal_10d": "cal_10d (8.0 sp)",
        "cal_12d": "cal_12d (7.0 sp)",
        "cal_14d": "cal_14d (6.0 sp)",
        "om_v1_T10": "om_v1_T10 (6.2 sp)",
        "om_v2_T10": "om_v2_T10 (5.2 sp)",
        "st_v1_T10": "st_v1_T10 (6.0 sp)",
        "st_v2_T10": "st_v2_T10 (5.2 sp)",
    }

    W, H = 560, 390
    ml, mr, mt, mb = 72, 168, 54, 54
    pw, ph = W - ml - mr, H - mt - mb
    cw = pw / len(slopes)
    ch = ph / len(revs)

    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="font-family:Segoe UI,Arial,sans-serif;background:#ffffff">',
        f'<text x="{ml+pw/2:.1f}" y="22" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0f172a">{title}</text>',
        f'<text x="{ml+pw/2:.1f}" y="39" text-anchor="middle" font-size="10" fill="#475569">{subtitle}</text>',
        f'<text x="{ml+pw/2:.1f}" y="{H-12}" text-anchor="middle" font-size="10.5" fill="#1f2937">Assumed bunch-damage slope k (per AUDPC unit)</text>',
        f'<text x="16" y="{mt+ph/2:.1f}" text-anchor="middle" font-size="10.5" fill="#1f2937" transform="rotate(-90 16 {mt+ph/2:.1f})">Disease-free gross revenue (€/ha)</text>',
    ]

    for r_idx, rev in enumerate(revs):
        y = mt + (len(revs) - 1 - r_idx) * ch
        elems.append(f'<text x="{ml-7}" y="{y+ch/2+3.5:.1f}" text-anchor="end" font-size="9.5" fill="#374151">{int(rev):,}</text>')
        for c_idx, sl in enumerate(slopes):
            x = ml + c_idx * cw
            w = grid[r_idx][c_idx]
            col = palette.get(w, "#4b5563")
            elems.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw:.1f}" height="{ch:.1f}" fill="{col}" stroke="#ffffff" stroke-width="1"/>')

    for c_idx, sl in enumerate(slopes):
        if c_idx in (0, 3, 6, 9, len(slopes) - 1):
            x = ml + (c_idx + 0.5) * cw
            elems.append(f'<text x="{x:.1f}" y="{mt+ph+16:.1f}" text-anchor="middle" font-size="9" fill="#374151">{sl:.4f}</text>')

    lx, ly = ml + pw + 12, mt + 10
    elems.append(f'<text x="{lx}" y="{ly}" font-size="10.2" font-weight="700" fill="#0f172a">Optimal Strategy</text>')
    for idx, (strat, pct) in enumerate(sens["winner_share_pct"].items()):
        yy = ly + 22 + idx * 22
        col = palette.get(strat, "#4b5563")
        elems.append(f'<rect x="{lx}" y="{yy-10}" width="11" height="11" fill="{col}"/>')
        elems.append(f'<text x="{lx+16}" y="{yy}" font-size="9.3" fill="#1f2937">{labels.get(strat, strat)}: {pct:.1f}%</text>')

    elems.append("</svg>")
    out_path.write_text("\n".join(elems), encoding="utf-8")
    return out_path


def build_fig3_economics() -> tuple[Path, Path]:
    raw = json.loads((ROOT / "data" / "v2_v102_errata_audit.json").read_text(encoding="utf-8"))
    eco = raw["semireal"]["economics_pooled"]
    p1 = _write_english_econ_svg(
        eco["unconstrained"],
        "(a) Unconstrained Net Return (€/ha)",
        "No copper cap; spray cost €55/ha",
        FIG_DIR / "fig3a_econ_unconstrained.svg",
    )
    p2 = _write_english_econ_svg(
        eco["eu_copper_050"],
        "(b) EU 2018/1981 Copper-Compliant Net Return",
        "Pooled ≤ 28 kg Cu/ha over 7 yr at 0.50 kg Cu/ha/spray",
        FIG_DIR / "fig3b_econ_eu_copper.svg",
    )
    return p1, p2


def main() -> int:
    f1 = build_fig1_semireal_pareto()
    print(f"Generated {f1}", flush=True)
    f3a, f3b = build_fig3_economics()
    print(f"Generated {f3a} and {f3b}", flush=True)
    f2, info = build_fig2_failure_timelines()
    print(f"Generated {f2}", flush=True)
    for k, d in info.items():
        print(f"\n=== {k}: {d['station']} {d['year']} ===", flush=True)
        print(f"om_v1 sprays={d['om_sprays_mean']}, om_aacpd={d['om_aacpd_mean']}, cal_{d['ref_cal_interval']}d_aacpd={d['cal_aacpd_mean']}", flush=True)
        print("om_v1 spray freq (% of 50 plots) by day offset:", d["spray_freq_pct"], flush=True)
        print("ref cal spray days:", d["ref_cal_days"], flush=True)
        # Top 10 daily new infection days under om_v1
        top_inf = sorted(enumerate(d["mean_new_inf_om_pct"]), key=lambda kv: -kv[1])[:10]
        print("Top 10 new-infection days (om_v1):", [
            (day, d["dates"][day], round(val, 3), f"sensLWD={d['sensor_lwd_h'][day]}h", f"omLWD={d['om_lwd_h'][day]}h", f"rain={d['station_rain_mm'][day]}mm")
            for day, val in top_inf
        ], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
