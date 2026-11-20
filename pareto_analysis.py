#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pareto_analysis.py
==================
Análise de fronteira de Pareto (Aplicações × AACPD com IC 95 % bootstrap)
para o Caminho A — agrometeorologia preventiva para míldio da videira
(*Plasmopara viticola*, CART de Kim et al. 2002 + previsão de 7 dias).

Separação estrita de amostras:
* `--mode dev-pareto`   : descrição na amostra de desenvolvimento (2022–2024,
                          Moselle & Bordeaux, 360 talhão-safras).
* `--mode oos-validate` : validação estritamente fora da amostra em anos nunca
                          vistos (2019–2021) + 3ª região inédita (Alsace/Colmar,
                          540 talhão-safras), usando ponto de operação CONGELADO.

Inclui a ÚNICA mudança fundamentada contra o agrupamento em anos chuvosos
(`residual_gate`): substitui o corte binário `4 d / 15 mm` por um portão
contínuo de cobertura residual estimada
    P_est(t) = 0.5^(dt / 7.0) * 0.5^(rain_since / 30.0) <= 0.45
com piso mínimo de 6 dias entre pulverizações.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import downy_mildew as dm
import epidemiology_assimilation as ea
import leaf_wetness as lw
import osse_benchmark as osse

log = logging.getLogger("pareto_analysis")

UTC = timezone.utc

FIXED_CALENDAR_INTERVALS: tuple[int, ...] = (7, 10, 12, 14)
FORECAST_SCORE_THRESHOLDS: tuple[float, ...] = (4.0, 6.0, 8.0, 10.0, 13.0)

# Ponto de operação CONGELADO após análise descritiva de 2022–2024 (maior ganho sobre a fronteira: -84,9 AACPD em T=10)
FROZEN_OPERATING_THRESHOLD: float = 10.0


@dataclass(frozen=True)
class ResidualGateConfig:
    """Portão físico de cobertura residual (única alteração contra agrupamento)."""
    min_floor_days: float = 6.0
    rule_half_life_days: float = 7.0   # distinto da verdade SEIR (5,5 ± 1,2 d)
    rule_washoff_mm: float = 30.0      # distinto da verdade SEIR (25 ± 8 mm)
    residual_reapply_max: float = 0.45
    lwd_method: str = "cart_kim2002"


def decide_forecast_residual_gate(
    obs_daily: pd.DataFrame,
    fc_daily: pd.DataFrame,
    last_spray: Optional[datetime],
    now: datetime,
    threshold_score: float,
    rain_since_last_spray_mm: float,
    gate_cfg: ResidualGateConfig,
) -> bool:
    """
    Regra preventiva `(c_v2)` com portão de cobertura residual:
    * Sem agrupamento em 4 dias: exige piso mínimo de 6 dias E cobertura
      residual estimada `P_est <= 0,45` (no tempo seco ~8 d; após chuva
      moderada/forte libera a partir de 6 d).
    * Só dispara se houver risco real previsto nos próximos 3–7 dias.
    """
    if last_spray is not None:
        days_since = (now - last_spray).total_seconds() / 86_400.0
        if days_since < gate_cfg.min_floor_days:
            return False
        p_est = (0.5 ** (days_since / gate_cfg.rule_half_life_days)) * (
            0.5 ** (rain_since_last_spray_mm / gate_cfg.rule_washoff_mm)
        )
        if p_est > gate_cfg.residual_reapply_max:
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
    fc_score = sv_fc_7d + 0.5 * sv_fc_3d
    return bool(fc_score >= threshold_score)


def _boot_mean_ci95(values: Sequence[float], n_boot: int = 5000, seed: int = 42) -> tuple[float, list[float]]:
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return round(float(arr.mean()), 3), [round(float(lo), 3), round(float(hi), 3)]


def _pareto_plot_worker(task: dict) -> dict:
    wdf: pd.DataFrame = task["wdf"]
    station_daily_full: pd.DataFrame = task["station_daily_full"]
    plot: osse.SeirPlotParams = task["plot"]
    true_wet: np.ndarray = task["true_wet"]
    season_start: datetime = task["season_start"]
    season_days: int = task["season_days"]
    eval_ts_list: list[datetime] = task["eval_ts_list"]
    eval_indices: list[int] = task["eval_indices"]
    local_tz_name: str = task["local_tz_name"]
    thresholds: Sequence[float] = task["thresholds"]
    include_v2: bool = task["include_v2"]
    lwd_method: str = task.get("lwd_method", "cart_kim2002")
    seed: int = task["seed"]

    tz = ZoneInfo(local_tz_name)
    rng = np.random.default_rng(seed)
    v1_cfg = osse.VineyardDecisionConfig(lwd_method=lwd_method)
    v2_cfg = ResidualGateConfig(lwd_method=lwd_method)

    # Gera previsões ruidosas uma única vez por talhão (comparação pareada limpa)
    obs_daily_steps: list[pd.DataFrame] = []
    fc_daily_steps: list[pd.DataFrame] = []
    for eval_ts in eval_ts_list:
        eval_pd = pd.Timestamp(eval_ts)
        fc_end_pd = eval_pd + pd.Timedelta(hours=168)
        eval_day = eval_ts.astimezone(tz).date()
        obs_daily_steps.append(station_daily_full[station_daily_full["day"] <= eval_day])
        fc_raw = osse._perturb_forecast(wdf[(wdf.index > eval_pd) & (wdf.index <= fc_end_pd)], rng)
        fc_daily_steps.append(
            dm.compute_downy_mildew_daily(fc_raw, lwd_method=v1_cfg.lwd_method, local_tz_name=local_tz_name)
        )

    def _eval_sprays(sprays: list[datetime]) -> dict:
        traj = osse.simulate_seir_trajectory(wdf, plot, sprays, true_wet)
        sevs = [float(traj[idx]) for idx in eval_indices]
        return {"aacpd": round(ea.aacpd(eval_ts_list, sevs), 4), "n_sprays": len(sprays)}

    out: dict[str, Any] = {"plot_id": plot.plot_id, "testemunha": _eval_sprays([])}

    # Calendários fixos reais (escolhidos ANTES da safra)
    for interval in FIXED_CALENDAR_INTERVALS:
        sprays = [season_start + timedelta(days=d, hours=2) for d in range(0, season_days, interval)]
        out[f"cal_{interval}d"] = _eval_sprays(sprays)

    # Regra (c) v1 (antes da correção de agrupamento) nos limiares da fronteira
    for thr in thresholds:
        sprays_v1: list[datetime] = []
        for eval_ts, obs_d, fc_d in zip(eval_ts_list, obs_daily_steps, fc_daily_steps):
            rain_since = 0.0
            if sprays_v1:
                rain_since = float(
                    wdf[(wdf.index > pd.Timestamp(sprays_v1[-1])) & (wdf.index <= pd.Timestamp(eval_ts))]["precip_mm"]
                    .fillna(0.0).sum()
                )
            if osse.decide_climate_forecast_washoff(
                obs_d, fc_d, sprays_v1[-1] if sprays_v1 else None, eval_ts, v1_cfg, thr, rain_since
            ):
                sprays_v1.append(eval_ts + timedelta(hours=2))
        out[f"fc_v1_T{thr:g}"] = _eval_sprays(sprays_v1)

    # Regra (c_v2) com portão de cobertura residual (anti-agrupamento)
    if include_v2:
        for thr in thresholds:
            sprays_v2: list[datetime] = []
            for eval_ts, obs_d, fc_d in zip(eval_ts_list, obs_daily_steps, fc_daily_steps):
                rain_since = 0.0
                if sprays_v2:
                    rain_since = float(
                        wdf[(wdf.index > pd.Timestamp(sprays_v2[-1])) & (wdf.index <= pd.Timestamp(eval_ts))]["precip_mm"]
                        .fillna(0.0).sum()
                    )
                if decide_forecast_residual_gate(
                    obs_d, fc_d, sprays_v2[-1] if sprays_v2 else None, eval_ts, thr, rain_since, v2_cfg
                ):
                    sprays_v2.append(eval_ts + timedelta(hours=2))
            out[f"fc_v2_T{thr:g}"] = _eval_sprays(sprays_v2)

    return out


def _interpolate_calendar_frontier(cal_points: Sequence[dict], target_sprays: float) -> Optional[float]:
    """Interpola a AACPD da fronteira de calendários fixos no mesmo eixo x (aplicações)."""
    pts = sorted(cal_points, key=lambda p: p["sprays_mean"])
    xs = [p["sprays_mean"] for p in pts]
    ys = [p["aacpd_mean"] for p in pts]
    if target_sprays < xs[0] or target_sprays > xs[-1]:
        return None
    return round(float(np.interp(target_sprays, xs, ys)), 3)


def summarize_pareto(rows: Sequence[dict], thresholds: Sequence[float], include_v2: bool) -> dict:
    cal_keys = [f"cal_{d}d" for d in FIXED_CALENDAR_INTERVALS]
    v1_keys = [f"fc_v1_T{thr:g}" for thr in thresholds]
    v2_keys = [f"fc_v2_T{thr:g}" for thr in thresholds] if include_v2 else []

    def _agg(key: str) -> dict:
        aacpds = [r[key]["aacpd"] for r in rows]
        sprays = [r[key]["n_sprays"] for r in rows]
        mean_a, ci_a = _boot_mean_ci95(aacpds)
        mean_s, ci_s = _boot_mean_ci95(sprays)
        return {
            "strategy": key,
            "n_plots": len(rows),
            "sprays_mean": mean_s,
            "sprays_ci95": ci_s,
            "aacpd_mean": mean_a,
            "aacpd_ci95": ci_a,
        }

    cal_pts = [_agg(k) for k in cal_keys]
    v1_pts = []
    for k in v1_keys:
        pt = _agg(k)
        ref = _interpolate_calendar_frontier(cal_pts, pt["sprays_mean"])
        pt["calendar_frontier_aacpd"] = ref
        pt["delta_vs_calendar_frontier"] = None if ref is None else round(pt["aacpd_mean"] - ref, 3)
        v1_pts.append(pt)

    v2_pts = []
    for k in v2_keys:
        pt = _agg(k)
        ref = _interpolate_calendar_frontier(cal_pts, pt["sprays_mean"])
        pt["calendar_frontier_aacpd"] = ref
        pt["delta_vs_calendar_frontier"] = None if ref is None else round(pt["aacpd_mean"] - ref, 3)
        v2_pts.append(pt)

    # Teste pareado direto contra o calendário fixo mais próximo em número de aplicações
    paired_vs_closest_cal: dict[str, dict] = {}
    for pt in v1_pts + v2_pts:
        closest_cal = min(cal_pts, key=lambda c: abs(c["sprays_mean"] - pt["sprays_mean"]))["strategy"]
        stats = osse.paired_comparison_stats(
            [r[pt["strategy"]]["aacpd"] for r in rows],
            [r[closest_cal]["aacpd"] for r in rows],
        )
        stats["compared_to"] = closest_cal
        stats["delta_sprays"] = round(
            pt["sprays_mean"] - next(c["sprays_mean"] for c in cal_pts if c["strategy"] == closest_cal), 3
        )
        paired_vs_closest_cal[pt["strategy"]] = stats

    return {
        "testemunha": _agg("testemunha"),
        "calendars": cal_pts,
        "forecast_v1": v1_pts,
        "forecast_v2": v2_pts,
        "paired_vs_closest_calendar": paired_vs_closest_cal,
    }


def write_pareto_svg(summary: dict, title: str, out_path: str | Path) -> Path:
    """Gera gráfico SVG autocontido da curva de Pareto (Aplicações × AACPD com IC 95 %)."""
    pts_all = summary["calendars"] + summary["forecast_v1"] + summary["forecast_v2"]
    xs = [p["sprays_mean"] for p in pts_all]
    y_los = [p["aacpd_ci95"][0] for p in pts_all]
    y_his = [p["aacpd_ci95"][1] for p in pts_all]

    x_min, x_max = min(xs) - 0.6, max(xs) + 0.6
    y_min, y_max = max(0.0, min(y_los) * 0.9), max(y_his) * 1.08
    W, H = 760, 460
    ml, mr, mt, mb = 78, 30, 48, 60
    pw, ph = W - ml - mr, H - mt - mb

    sx = lambda v: ml + (v - x_min) / max(x_max - x_min, 1e-6) * pw
    sy = lambda v: mt + ph - (v - y_min) / max(y_max - y_min, 1e-6) * ph

    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" style="font-family:Segoe UI,Arial,sans-serif;background:#fff">',
        f'<text x="{W/2:.1f}" y="26" text-anchor="middle" font-size="15" font-weight="600" fill="#1f2937">{title}</text>',
        f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" stroke="#374151" stroke-width="1.2"/>',
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" stroke="#374151" stroke-width="1.2"/>',
        f'<text x="{ml+pw/2:.1f}" y="{H-14}" text-anchor="middle" font-size="12" fill="#374151">Aplicações médias na safra (75 dias)</text>',
        f'<text x="20" y="{mt+ph/2:.1f}" text-anchor="middle" font-size="12" fill="#374151" transform="rotate(-90 20 {mt+ph/2:.1f})">AACPD média (% × dia, IC 95 %)</text>',
    ]

    # Grades simples
    for tick_x in np.linspace(round(x_min + 0.5), round(x_max - 0.5), 6):
        px = sx(tick_x)
        elems.append(f'<line x1="{px:.1f}" y1="{mt}" x2="{px:.1f}" y2="{mt+ph}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
        elems.append(f'<text x="{px:.1f}" y="{mt+ph+18}" text-anchor="middle" font-size="10" fill="#4b5563">{tick_x:.1f}</text>')
    for tick_y in np.linspace(y_min, y_max, 6):
        py = sy(tick_y)
        elems.append(f'<line x1="{ml}" y1="{py:.1f}" x2="{ml+pw}" y2="{py:.1f}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
        elems.append(f'<text x="{ml-8}" y="{py+3:.1f}" text-anchor="end" font-size="10" fill="#4b5563">{tick_y:.0f}</text>')

    def _draw_series(pts: Sequence[dict], color: str, dash: str = ""):
        if not pts:
            return
        ordered = sorted(pts, key=lambda p: p["sprays_mean"])
        path = " ".join(f"{'M' if i == 0 else 'L'}{sx(p['sprays_mean']):.1f},{sy(p['aacpd_mean']):.1f}" for i, p in enumerate(ordered))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        elems.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2"{dash_attr}/>')
        for p in ordered:
            px, py = sx(p["sprays_mean"]), sy(p["aacpd_mean"])
            ylo, yhi = sy(p["aacpd_ci95"][0]), sy(p["aacpd_ci95"][1])
            elems.append(f'<line x1="{px:.1f}" y1="{yhi:.1f}" x2="{px:.1f}" y2="{ylo:.1f}" stroke="{color}" stroke-width="1.4" opacity="0.65"/>')
            elems.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{color}"/>')
            lbl = p["strategy"].replace("cal_", "").replace("fc_v1_", "v1:").replace("fc_v2_", "v2:")
            elems.append(f'<text x="{px+6:.1f}" y="{py-6:.1f}" font-size="9.5" fill="{color}">{lbl}</text>')

    _draw_series(summary["calendars"], "#111827")
    _draw_series(summary["forecast_v1"], "#d97706", dash="5,3")
    _draw_series(summary["forecast_v2"], "#059669")

    # Legenda
    lx, ly = ml + pw - 235, mt + 14
    elems.append(f'<rect x="{lx-8}" y="{ly-12}" width="235" height="62" fill="#fff" fill-opacity="0.9" stroke="#d1d5db"/>')
    for idx, (col, text) in enumerate((
        ("#111827", "Calendários fixos (7, 10, 12, 14 d)"),
        ("#d97706", "Previsão v1 (lavagem 4 d / 15 mm)"),
        ("#059669", "Previsão v2 (portão residual >= 6 d)"),
    )):
        yy = ly + idx * 18
        elems.append(f'<circle cx="{lx+4}" cy="{yy-3}" r="4" fill="{col}"/>')
        elems.append(f'<text x="{lx+14}" y="{yy}" font-size="10.5" fill="#1f2937">{text}</text>')

    elems.append("</svg>")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(elems), encoding="utf-8")
    return out


def run_pareto_suite(
    regions: Sequence[str],
    years: Sequence[int],
    thresholds: Sequence[float] = FORECAST_SCORE_THRESHOLDS,
    include_v2: bool = True,
    lwd_method: str = "cart_kim2002",
    n_plots: int = 60,
    season_days: int = 75,
    base_seed: int = 20240101,
    max_workers: Optional[int] = None,
) -> dict:
    all_rows: list[dict] = []
    cohorts: list[dict] = []
    workers = max_workers if max_workers is not None else max((os.cpu_count() or 2) - 2, 1)

    for r_i, region_key in enumerate(regions):
        reg = dm.VINEYARD_REGIONS[region_key]
        tz = ZoneInfo(reg["tz"])
        for y_i, year in enumerate(years):
            log.info("Pareto (%s): %s %d ...", lwd_method, region_key, year)
            weather = dm.fetch_rich_historical_weather(
                f"{year}-05-01", f"{year}-08-05", reg["latitude"], reg["longitude"]
            )
            wdf = lw.normalize_rich_weather(weather)
            station_daily_full = dm.compute_downy_mildew_daily(
                wdf, lwd_method=lwd_method, local_tz_name=reg["tz"]
            )
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

            cohort_seed = base_seed + r_i * 100_000 + y_i * 10_000
            plots = osse._build_seir_plots(n_plots=n_plots, seed=cohort_seed)
            tasks = [
                {
                    "wdf": wdf,
                    "station_daily_full": station_daily_full,
                    "plot": plot,
                    "true_wet": osse._canopy_true_wetness(
                        wdf, plot.micro_dpd_bias_c, plot.wind_shelter, np.random.default_rng(cohort_seed + 10_000 + i)
                    ),
                    "season_start": season_start,
                    "season_days": season_days,
                    "eval_ts_list": eval_ts_list,
                    "eval_indices": eval_indices,
                    "local_tz_name": reg["tz"],
                    "thresholds": list(thresholds),
                    "include_v2": include_v2,
                    "lwd_method": lwd_method,
                    "seed": cohort_seed + i * 131,
                }
                for i, plot in enumerate(plots)
            ]
            if workers > 1 and len(tasks) >= 4:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(_pareto_plot_worker, tasks))
            else:
                rows = [_pareto_plot_worker(t) for t in tasks]

            all_rows.extend(rows)
            cohorts.append({
                "region_key": region_key,
                "region": reg["name"],
                "year": year,
                "summary": summarize_pareto(rows, thresholds, include_v2),
            })

    pooled = summarize_pareto(all_rows, thresholds, include_v2)
    return {
        "regions": list(regions),
        "years": list(years),
        "lwd_method": lwd_method,
        "n_plots_per_cohort": n_plots,
        "total_plot_seasons": len(all_rows),
        "base_seed": base_seed,
        "thresholds": list(thresholds),
        "include_v2": include_v2,
        "residual_gate_config": ResidualGateConfig(lwd_method=lwd_method).__dict__ if include_v2 else None,
        "pooled": pooled,
        "cohorts": cohorts,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fronteira de Pareto e validação fora da amostra (Caminho A).")
    parser.add_argument("--mode", choices=("dev-pareto", "oos-validate", "oos-2016-2018"), required=True)
    parser.add_argument("--lwd-method", choices=lw.VALID_METHODS, default="cart_kim2002")
    parser.add_argument("--n-plots", type=int, default=60)
    parser.add_argument("--out-dir", default="data/fase2")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "dev-pareto":
        res = run_pareto_suite(
            regions=("moselle_lu", "bordeaux_fr"),
            years=(2022, 2023, 2024),
            thresholds=FORECAST_SCORE_THRESHOLDS,
            include_v2=False,
            lwd_method=args.lwd_method,
            n_plots=args.n_plots,
            base_seed=20240101,
        )
        json_path = out_dir / "pareto_dev_2022_2024.json"
        svg_path = out_dir / "pareto_dev_2022_2024.svg"
        write_pareto_svg(res["pooled"], f"Curva de Pareto (Dev 2022–2024, {args.lwd_method}, N=360)", svg_path)
    elif args.mode == "oos-validate":
        res = run_pareto_suite(
            regions=("moselle_lu", "bordeaux_fr", "alsace_fr"),
            years=(2019, 2020, 2021),
            thresholds=(FROZEN_OPERATING_THRESHOLD,),
            include_v2=True,
            lwd_method=args.lwd_method,
            n_plots=args.n_plots,
            base_seed=20190101,
        )
        json_path = out_dir / "pareto_oos_2019_2021.json"
        svg_path = out_dir / "pareto_oos_2019_2021.svg"
        write_pareto_svg(res["pooled"], f"Validação OOS (2019–2021, {args.lwd_method}, N=540)", svg_path)
    else:
        # Item 2: validação em anos intactos (2016–2018) com o estimador vencedor no sensor real
        res = run_pareto_suite(
            regions=("moselle_lu", "bordeaux_fr", "alsace_fr"),
            years=(2016, 2017, 2018),
            thresholds=(FROZEN_OPERATING_THRESHOLD,),
            include_v2=True,
            lwd_method=args.lwd_method,
            n_plots=args.n_plots,
            base_seed=20160101,
        )
        json_path = out_dir / f"pareto_oos_2016_2018_{args.lwd_method}.json"
        svg_path = out_dir / f"pareto_oos_2016_2018_{args.lwd_method}.svg"
        write_pareto_svg(res["pooled"], f"Validação OOS Intacta (2016–2018, {args.lwd_method}, N=540)", svg_path)

    json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res["pooled"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
