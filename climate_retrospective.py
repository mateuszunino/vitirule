#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climate_retrospective.py
========================
Fase 2 do projeto (BRIEFING.md seção 6):
1. Carrega ou baixa 24 meses de clima horário real de São José/SC
   (-27.5969, -48.6367) — aceita CSV da Epagri/Ciram ou Open-Meteo Archive.
2. Calcula a retrospectiva diária, mensal e sazonal de TOM-CAST (DSV) e
   Wallin (SV) usando diretamente `decision_engine.compute_dsv_daily_rows` e
   `epidemiology_assimilation` (sem duplicar fórmulas).
3. Avalia a calibração do intervalo de 95 % do modelo epidemiológico em
   epidemias simuladas (critério BRIEFING.md seção 7: 90 % a 98 %).
4. Roda o benchmark multi-estação (`testemunha` x `calendario_semanal` x `dss`)
   e análise de sensibilidade de limiares usando o simulador sobre estações
   históricas reais de Santa Catarina.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import decision_engine as de
import epidemiology_assimilation as ea
import simulator as sim

log = logging.getLogger("climate_retrospective")

UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def season_south(month: int) -> str:
    """Estação meteorológica no Hemisfério Sul."""
    if month in (12, 1, 2):
        return "Verao"
    if month in (3, 4, 5):
        return "Outono"
    if month in (6, 7, 8):
        return "Inverno"
    return "Primavera"


def save_weather_csv(rows: Sequence[dict], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=("ts", "temp_c", "rh_pct", "precip_mm"))
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "ts": r["ts"],
                "temp_c": r.get("temp_c"),
                "rh_pct": r.get("rh_pct"),
                "precip_mm": r.get("precip_mm"),
            })
    return out


def load_or_fetch_24m_weather(
    cache_path: str | Path = "data/weather_history_24m_open_meteo.csv",
    epagri_csv: Optional[str | Path] = None,
    end_date: Optional[date] = None,
    months: int = 24,
) -> tuple[list[dict], str]:
    """
    Retorna `(weather_rows, source_label)`.
    Prioriza CSV real da Epagri se fornecido; senão lê o cache local ou baixa
    os últimos 24 meses de São José/SC pela Open-Meteo Archive API (reanálise).
    """
    if epagri_csv:
        rows = sim.load_weather_from_csv(epagri_csv)
        return rows, f"epagri_csv:{Path(epagri_csv).name}"

    cache = Path(cache_path)
    if cache.is_file():
        return sim.load_weather_from_csv(cache), f"open_meteo_archive_cache:{cache.name}"

    # Open-Meteo Archive costuma ter ~5 dias de latência em relação à data atual
    ref_end = end_date or (datetime.now(UTC).date() - timedelta(days=7))
    # Se o relógio da máquina estiver no futuro em relação ao archive, cai de forma segura
    ref_start = ref_end - timedelta(days=int(round(months * 30.4375)))
    rows = sim.fetch_open_meteo_historical(ref_start, ref_end)
    save_weather_csv(rows, cache)
    return rows, f"open_meteo_archive:{ref_start.isoformat()}..{ref_end.isoformat()}"


def _count_climate_triggered_sprays(
    daily_df: pd.DataFrame,
    disease: str,
    dsv_threshold: int = de.TOMCAST_DSV_THRESHOLD,
    wallin_7d_threshold: int = de.WALLIN_7D_THRESHOLD,
    min_interval_days: int = int(de.MIN_SPRAY_INTERVAL_DAYS),
) -> int:
    """Conta quantas aplicações seriam disparadas puramente pelo gatilho climático."""
    sprays = 0
    last_spray_idx: Optional[int] = None
    dsv_acc = 0
    wallins = daily_df["wallin_sv"].to_numpy(dtype=int)
    dsvs = daily_df["tomcast_dsv"].to_numpy(dtype=int)

    for i in range(len(daily_df)):
        if last_spray_idx is not None and (i - last_spray_idx) < min_interval_days:
            continue
        if disease == "pinta_preta":
            dsv_acc += int(dsvs[i])
            if dsv_acc >= dsv_threshold:
                sprays += 1
                last_spray_idx = i
                dsv_acc = 0
        else:
            w7 = int(wallins[max(0, i - 6): i + 1].sum())
            if w7 >= wallin_7d_threshold:
                sprays += 1
                last_spray_idx = i
    return sprays


def compute_retrospective(weather: Sequence[dict], station_id: str = "sj_vasos") -> dict:
    """
    Calcula a retrospectiva diária, mensal e sazonal de TOM-CAST e Wallin
    a partir da série horária, reutilizando `decision_engine.compute_dsv_daily_rows`.
    """
    wdf = ea.weather_frame(weather)
    if wdf.empty:
        raise ValueError("série climática vazia")

    dsv_rows = de.compute_dsv_daily_rows(wdf, station_id=station_id, kind="observed")
    daily = pd.DataFrame(dsv_rows)
    daily["day_dt"] = pd.to_datetime(daily["day"])
    daily["year_month"] = daily["day_dt"].dt.strftime("%Y-%m")
    daily["month"] = daily["day_dt"].dt.month
    daily["season"] = daily["month"].map(season_south)

    # Estatísticas térmicas e hídricas diárias (janela 12h-12h local, igual ao TOM-CAST)
    daily_temp = {}
    daily_rh = {}
    daily_rain = {}
    for day_ts, block in ea._daily_windows(wdf, 12):
        key = day_ts.date()
        daily_temp[key] = float(block["temp_c"].mean()) if block["temp_c"].notna().any() else np.nan
        daily_rh[key] = float(block["rh_pct"].mean()) if block["rh_pct"].notna().any() else np.nan
        daily_rain[key] = float(block["precip_mm"].fillna(0.0).sum())
    daily["temp_mean_c"] = daily["day"].map(daily_temp)
    daily["rh_mean_pct"] = daily["day"].map(daily_rh)
    daily["precip_mm"] = daily["day"].map(daily_rain)

    monthly_rows: list[dict] = []
    for ym, grp in daily.groupby("year_month"):
        monthly_rows.append({
            "year_month": ym,
            "season": season_south(int(ym.split("-")[1])),
            "n_days": int(len(grp)),
            "temp_mean_c": round(float(grp["temp_mean_c"].mean()), 2),
            "rh_mean_pct": round(float(grp["rh_mean_pct"].mean()), 1),
            "precip_total_mm": round(float(grp["precip_mm"].sum()), 1),
            "wet_hours_mean": round(float(grp["wet_hours"].mean()), 2),
            "tomcast_dsv_sum": int(grp["tomcast_dsv"].sum()),
            "tomcast_days_ge2": int((grp["tomcast_dsv"] >= 2).sum()),
            "wallin_sv_sum": int(grp["wallin_sv"].sum()),
            "wallin_days_ge1": int((grp["wallin_sv"] >= 1).sum()),
            "est_sprays_tomcast": _count_climate_triggered_sprays(grp, "pinta_preta"),
            "est_sprays_wallin": _count_climate_triggered_sprays(grp, "requeima"),
        })

    season_order = ("Verao", "Outono", "Inverno", "Primavera")
    seasonal_rows: list[dict] = []
    for s in season_order:
        grp = daily[daily["season"] == s]
        if grp.empty:
            continue
        seasonal_rows.append({
            "season": s,
            "n_days": int(len(grp)),
            "temp_mean_c": round(float(grp["temp_mean_c"].mean()), 2),
            "rh_mean_pct": round(float(grp["rh_mean_pct"].mean()), 1),
            "wet_hours_per_day": round(float(grp["wet_hours"].mean()), 2),
            "tomcast_dsv_per_30d": round(float(grp["tomcast_dsv"].sum()) / len(grp) * 30.0, 2),
            "wallin_sv_per_30d": round(float(grp["wallin_sv"].sum()) / len(grp) * 30.0, 2),
            "tomcast_days_ge2_pct": round(100.0 * float((grp["tomcast_dsv"] >= 2).mean()), 1),
            "wallin_days_ge1_pct": round(100.0 * float((grp["wallin_sv"] >= 1).mean()), 1),
        })

    return {
        "n_hours": int(len(wdf)),
        "n_days": int(len(daily)),
        "period_start": daily["day"].min().isoformat(),
        "period_end": daily["day"].max().isoformat(),
        "monthly": monthly_rows,
        "seasonal": seasonal_rows,
        "daily_df": daily,
    }


def evaluate_ci95_calibration(
    weather: Sequence[dict],
    disease: str = "pinta_preta",
    n_trials: int = 80,
    seed: int = 20261120,
    n_draws: int = 1500,
) -> dict:
    """
    Mede a cobertura empírica do intervalo de 95 % na projeção de 7 dias
    em epidemias simuladas (critério BRIEFING.md seção 7: 90 % a 98 %).
    """
    wdf = ea.weather_frame(weather)
    t_min = wdf.index.min().to_pydatetime()
    t_max = wdf.index.max().to_pydatetime()
    span_days = int((t_max - t_min).total_seconds() // 86_400)
    if span_days < 25:
        raise ValueError("clima precisa de pelo menos 25 dias para teste de cobertura IC 95 %")

    params = ea.PATHOGENS[disease]
    rng = np.random.default_rng(seed)
    covered_7d = 0
    covered_r = 0
    max_offset = max(1, span_days - 24)
    base_cfg = ea.AssimilationConfig(n_draws=n_draws, fc_sigma0=0.0, fc_sigma_per_day=0.0)

    for i in range(n_trials):
        offset_days = int(rng.integers(0, max_offset))
        t0 = t_min + timedelta(days=offset_days)
        cut = t0 + timedelta(days=14)
        t_end = cut + timedelta(days=7)
        window = wdf[(wdf.index >= pd.Timestamp(t0)) & (wdf.index <= pd.Timestamp(t_end))]
        clock = ea.build_clock(window, t0, t_end, disease, base_cfg)
        if clock.tau(t_end)[0] < 1.0:
            continue

        r_true = float(params["r_prior"] * math.exp(rng.normal(0.0, 0.35)))
        y0_true = float(np.clip(params["y0_prior_pct"] * math.exp(rng.normal(0.0, 0.35)), 0.08, 1.5))

        obs = []
        for d in range(0, 15, 2):
            ts = t0 + timedelta(days=d)
            truth = float(ea.curve("logistic", clock.tau(ts)[0], r_true, y0_true, 100.0))
            sd = math.sqrt(0.30 ** 2 + (0.10 * truth) ** 2)
            obs.append({
                "ts": ts.isoformat(),
                "severity_pct": float(np.clip(truth + rng.normal(0.0, sd), 0.0, 100.0)),
                "severity_sd_pct": 0.0,
            })

        w_obs = window[window.index <= pd.Timestamp(cut)]
        w_fc = window[window.index > pd.Timestamp(cut)]
        res = ea.assimilate(
            unit_id="V11",
            disease=disease,
            observations=obs,
            weather_observed=w_obs,
            weather_forecast=w_fc,
            config=ea.AssimilationConfig(n_draws=n_draws, seed=seed + i),
        )
        truth_7d = float(ea.curve("logistic", clock.tau(t_end)[0], r_true, y0_true, 100.0))
        last_pt = res["projection"][-1]
        if last_pt["y_lo95"] <= truth_7d <= last_pt["y_hi95"]:
            covered_7d += 1
        r_lo, r_hi = res["params"]["r_ci95"]
        if r_lo <= r_true <= r_hi:
            covered_r += 1

    rate_7d = covered_7d / n_trials
    rate_r = covered_r / n_trials
    return {
        "disease": disease,
        "n_trials": n_trials,
        "coverage_7d_ci95": round(rate_7d, 4),
        "coverage_r_ci95": round(rate_r, 4),
        "meets_90_98_target": bool(0.90 <= rate_7d <= 0.98),
    }


def run_multiseason_benchmark(
    weather: Sequence[dict],
    season_days: int = 42,
    seed: int = 20261120,
    n_draws: int = 400,
) -> list[dict]:
    """
    Roda `simulator.compare_strategies` sobre 4 janelas reais (Verão, Outono,
    Inverno, Primavera) para `pinta_preta` e `requeima` (BRIEFING.md Fase 3.5).
    """
    wdf = ea.weather_frame(weather)
    t_min = wdf.index.min().tz_convert(LOCAL_TZ)
    t_max = wdf.index.max().tz_convert(LOCAL_TZ)

    # Escolhe uma janela de (season_days + 10) dias representativa de cada estação
    target_months = {"Verao": 1, "Outono": 4, "Inverno": 7, "Primavera": 10}
    windows: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    for s_name, m in target_months.items():
        candidates = wdf[wdf.index.tz_convert(LOCAL_TZ).month == m]
        if candidates.empty:
            continue
        # Pega o primeiro instante do mês mais recente que ainda tenha season_days+10 à frente
        years = sorted(candidates.index.tz_convert(LOCAL_TZ).year.unique(), reverse=True)
        for yr in years:
            start_local = pd.Timestamp(year=int(yr), month=m, day=1, tz=LOCAL_TZ)
            end_local = start_local + pd.Timedelta(days=season_days + 10)
            if start_local >= t_min and end_local <= t_max:
                windows.append((f"{s_name}_{yr}", start_local.tz_convert("UTC"), end_local.tz_convert("UTC")))
                break

    results: list[dict] = []
    for label, start_utc, end_utc in windows:
        sub = wdf[(wdf.index >= start_utc) & (wdf.index <= end_utc)]
        sub_rows = [
            {
                "ts": ts.isoformat(),
                "temp_c": None if pd.isna(r.temp_c) else float(r.temp_c),
                "rh_pct": None if pd.isna(r.rh_pct) else float(r.rh_pct),
                "precip_mm": 0.0 if pd.isna(r.precip_mm) else float(r.precip_mm),
            }
            for ts, r in sub.iterrows()
        ]
        for disease in ("pinta_preta", "requeima"):
            cfg = sim.SimulationConfig(
                disease=disease,
                season_days=season_days,
                eval_cadence_days=(2, 3),
                seed=seed,
                n_draws=n_draws,
            )
            cmp_res = sim.compare_strategies(sub_rows, cfg)
            st = cmp_res["strategies"]
            results.append({
                "season_window": label,
                "disease": disease,
                "start_date": start_utc.tz_convert(LOCAL_TZ).date().isoformat(),
                "testemunha_aacpd": st["testemunha"]["aacpd_mean"],
                "calendario_aacpd": st["calendario_semanal"]["aacpd_mean"],
                "calendario_sprays": st["calendario_semanal"]["sprays_mean"],
                "dss_aacpd": st["dss"]["aacpd_mean"],
                "dss_sprays": st["dss"]["sprays_mean"],
                "spray_saving_pct": round(
                    100.0 * (1.0 - st["dss"]["sprays_mean"] / max(st["calendario_semanal"]["sprays_mean"], 1e-9)), 1
                ),
                "aacpd_reduction_vs_control_pct": round(
                    100.0 * (1.0 - st["dss"]["aacpd_mean"] / max(st["testemunha"]["aacpd_mean"], 1e-9)), 1
                ),
            })
    return results


def _write_csv(rows: Sequence[dict], path: str | Path) -> None:
    if not rows:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Retrospectiva climática de 24 meses e validação Fase 2.")
    parser.add_argument("--epagri-csv", help="CSV histórico da Epagri/Ciram (opcional)")
    parser.add_argument("--cache", default="data/weather_history_24m_open_meteo.csv")
    parser.add_argument("--end-date", help="data final YYYY-MM-DD (padrão: 2026-11-12 ou hoje-7d)")
    parser.add_argument("--skip-ci95", action="store_true")
    parser.add_argument("--skip-benchmark", action="store_true")
    parser.add_argument("--ci95-trials", type=int, default=60)
    parser.add_argument("--out-dir", default="data/fase2")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    end_dt = date.fromisoformat(args.end_date) if args.end_date else None
    weather, source_label = load_or_fetch_24m_weather(
        cache_path=args.cache, epagri_csv=args.epagri_csv, end_date=end_dt
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    retro = compute_retrospective(weather)
    _write_csv(retro["monthly"], out_dir / "retrospectiva_24m_mensal.csv")
    _write_csv(retro["seasonal"], out_dir / "retrospectiva_24m_sazonal.csv")

    report: dict[str, Any] = {
        "source": source_label,
        "period_start": retro["period_start"],
        "period_end": retro["period_end"],
        "n_hours": retro["n_hours"],
        "n_days": retro["n_days"],
        "seasonal": retro["seasonal"],
    }

    if not args.skip_ci95:
        report["ci95_calibration"] = [
            evaluate_ci95_calibration(weather, disease="pinta_preta", n_trials=args.ci95_trials),
            evaluate_ci95_calibration(weather, disease="requeima", n_trials=args.ci95_trials),
        ]

    if not args.skip_benchmark:
        bench = run_multiseason_benchmark(weather)
        _write_csv(bench, out_dir / "benchmark_multiestacao.csv")
        report["multiseason_benchmark"] = bench

    (out_dir / "resumo_fase2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
