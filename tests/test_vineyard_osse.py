# -*- coding: utf-8 -*-
"""
Testes de agrometeorologia (molhamento foliar), míldio da videira
(*Plasmopara viticola*) e OSSE justo com modelo SEIR mal-especificado.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import downy_mildew as dm
import leaf_wetness as lw
import osse_benchmark as osse

UTC = timezone.utc


def _rich_synthetic_weather(days: int = 35, seed: int = 10) -> list[dict]:
    rng = np.random.default_rng(seed)
    start = datetime(2025, 5, 1, 0, tzinfo=UTC)
    rows = []
    for h in range(1, 24 * days + 1):
        ts = start + timedelta(hours=h)
        hr = (ts.hour + 2) % 24
        wave = math.sin((hr - 9) / 24.0 * 2.0 * math.pi)
        rain = float(rng.random() < 0.08) * float(rng.gamma(2.0, 2.2))
        temp = 19.0 + 5.5 * wave + float(rng.normal(0.0, 0.8))
        rh = float(np.clip(76.0 - 18.0 * wave + (15.0 if rain > 0 else 0.0) + rng.normal(0.0, 3.0), 30.0, 100.0))
        td = float(lw.magnus_dewpoint_c(np.array([temp]), np.array([rh]))[0])
        wind = float(max(0.3, 2.8 + 1.2 * wave + rng.normal(0.0, 0.6)))
        rad = float(max(0.0, 650.0 * max(0.0, math.sin((hr - 6) / 12.0 * math.pi)))) if 6 <= hr <= 18 else 0.0
        rows.append({
            "ts": ts.isoformat(),
            "temp_c": round(temp, 2),
            "rh_pct": round(rh, 1),
            "dewpoint_c": round(td, 2),
            "precip_mm": round(rain, 2),
            "wind_ms": round(wind, 2),
            "rad_wm2": round(rad, 1),
        })
    return rows


def test_leaf_wetness_models_discriminate_better_than_rh85():
    # Noite úmida com vento moderado (UR = 86 %, DPD = 2,3 °C, vento 10m = 5 m/s) -> rh85 acende, CART/DPD não
    weather = [
        {
            "ts": (datetime(2025, 6, 1, 0, tzinfo=UTC) + timedelta(hours=h)).isoformat(),
            "temp_c": 20.0,
            "rh_pct": 86.0,
            "precip_mm": 0.0,
            "wind_ms": 5.0,
            "rad_wm2": 0.0,
        }
        for h in range(12)
    ]
    w_rh85 = lw.estimate_leaf_wetness(weather, method="rh85")
    w_dpd = lw.estimate_leaf_wetness(weather, method="dpd_hysteresis")
    w_cart = lw.estimate_leaf_wetness(weather, method="cart_kim2002")
    assert w_rh85.sum() == 12.0
    assert w_dpd.sum() == 0.0
    assert w_cart.sum() == 0.0

    # Com chuva >= 0,1 mm/h, todos os modelos marcam hora molhada
    rainy = [dict(weather[0], precip_mm=0.5)]
    for m in lw.VALID_METHODS:
        assert float(lw.estimate_leaf_wetness(rainy, method=m).iloc[0]) == 1.0


def test_downy_mildew_goidanich_and_daily_indices():
    # Ótimo ~23 °C -> ~25 %/dia (~4 dias de incubação); fora de [8, 30] -> 0
    assert 24.0 <= dm.goidanich_daily_incubation_pct(23.0, 85.0) <= 25.5
    assert 5.0 <= dm.goidanich_daily_incubation_pct(12.0, 85.0) <= 10.0
    assert dm.goidanich_daily_incubation_pct(7.5, 90.0) == 0.0
    assert dm.goidanich_daily_incubation_pct(31.0, 90.0) == 0.0

    weather = _rich_synthetic_weather(days=15, seed=3)
    daily = dm.compute_downy_mildew_daily(weather, lwd_method="cart_kim2002", local_tz_name="Europe/Luxembourg")
    assert len(daily) >= 14
    assert {"lwd_hours", "rule_3_10", "incubation_pct", "secondary_sv"}.issubset(daily.columns)
    assert daily["secondary_sv"].between(0, 4).all()


def test_seir_washoff_and_fair_equal_budget_osse():
    weather = _rich_synthetic_weather(days=45, seed=21)
    wdf = lw.normalize_rich_weather(weather)
    plot = osse.SeirPlotParams(
        plot_id="P01", beta_max=0.06, initial_exposed=0.004,
        tmin_shift_c=1.0, topt_shift_c=-1.0, micro_dpd_bias_c=-0.3,
        wind_shelter=0.65, washoff_mm=15.0,
    )
    true_wet = lw.estimate_leaf_wetness(wdf, method="cart_kim2002").to_numpy()
    # Sem spray vs com spray no dia 6
    t0 = wdf.index[0].to_pydatetime()
    traj_none = osse.simulate_seir_trajectory(wdf, plot, [], true_wet)
    traj_spray = osse.simulate_seir_trajectory(wdf, plot, [t0 + timedelta(days=6)], true_wet)
    assert traj_spray[-1] < traj_none[-1]

    # OSSE completo com 4 braços de orçamento igual + estatística pareada (bootstrap + Wilcoxon)
    res = osse.run_fair_osse(
        weather, region_key="moselle_lu", season_days=30, n_plots=4, seed=21, n_draws=200, max_workers=1
    )
    st = res["strategies"]
    assert set(st.keys()) == {
        "testemunha",
        "uniform_calendar",
        "climate_reactive",
        "climate_forecast_washoff",
        "closed_loop_dss",
        "weekly_calendar",
    }
    # Orçamento de aplicações entre DSS e calendário uniforme deve ser EXATAMENTE igual
    assert st["uniform_calendar"]["sprays_mean"] == st["closed_loop_dss"]["sprays_mean"]
    assert len(res["lwd_comparison"]) == 4
    # Verifica presença das estatísticas pareadas e do trade-off contra o calendário semanal
    assert "d_minus_c_assimilation_value" in res["paired_contrasts"]
    assert "ci95_bootstrap" in res["paired_contrasts"]["d_minus_a_dss_vs_uniform"]
    assert "wilcoxon_p" in res["paired_contrasts"]["d_minus_c_assimilation_value"]
    assert "closed_loop_dss_vs_weekly" in res["tradeoffs_vs_weekly"]
    # Garante ausência de vazamento: regra fixa em 15 mm, verdade SEIR centrada em 25 mm
    assert res["rule_config"]["washoff_override_mm"] == 15.0
