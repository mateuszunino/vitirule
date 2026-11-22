"""
Testes unitarios sinteticos de `vitirule_v2/metrics.py` (Fase 3):
- Pareamento temporal um-para-um dentro das tolerancias pre-registradas
- Atraso com sinal (positivo = candidata atrasada, negativo = antecipada)
- Razao de alarmes falsos (FAR), alertas perdidos e F1
- Concordancia de classes de severidade de Mills
- Modelo diario de custo-perda com acertos negativos e verificacao nos limites
  (informacao perfeita V=1, sempre/nunca pulverizar V=0)
- Bootstrap em bloco por estacao e omissao automatica de IC quando n < 3
- Criterio binario pre-registrado de usabilidade
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from vitirule_v2.metrics import (
    MATCH_TOLERANCES_HOURS,
    aggregate_station_metrics_with_bootstrap,
    compute_daily_cost_loss,
    evaluate_usability,
    match_events_one_to_one,
    mills_severity_concordance,
)

UTC = timezone.utc


class TestEventMatchingAndSignedLag:
    def test_one_to_one_matching_within_2d_and_signed_lag_convention(self):
        refs = [date(2023, 5, 10), date(2023, 5, 20), date(2023, 6, 1)]
        # Candidata: +1 dia tarde em 10/05, -2 dias cedo em 20/05, perde 01/06, e gera 1 alarme falso em 15/06
        cands = [date(2023, 5, 11), date(2023, 5, 18), date(2023, 6, 15)]
        res = match_events_one_to_one(refs, cands, tolerance_hours=MATCH_TOLERANCES_HOURS["rule_3_10"])
        assert (res.tp, res.fp, res.fn) == (2, 1, 1)
        assert res.missed_rate == pytest.approx(1 / 3, abs=1e-4)
        assert res.far == pytest.approx(1 / 3, abs=1e-4)
        assert res.f1 == pytest.approx(2 / 3, abs=1e-4)
        # Lags com sinal: +1.0 (atraso) e -2.0 (antecipacao) -> mediana -0.5
        assert [p[2] for p in res.matched_pairs] == [1.0, -2.0]
        assert res.median_lag_days == pytest.approx(-0.5)

    def test_hourly_mills_matching_respects_24h_boundary(self):
        t0 = datetime(2023, 4, 20, 6, 0, tzinfo=UTC)
        refs = [t0, t0 + timedelta(days=5)]
        # Primeiro candidato exatamente +24h depois (pareia, lag=+1.0d); segundo +25h (fora da tolerancia!)
        cands = [t0 + timedelta(hours=24), t0 + timedelta(days=5, hours=25)]
        res = match_events_one_to_one(refs, cands, tolerance_hours=MATCH_TOLERANCES_HOURS["mills_revised"])
        assert (res.tp, res.fp, res.fn) == (1, 1, 1)
        assert res.matched_pairs[0][2] == pytest.approx(1.0)

    def test_greedy_matching_picks_closest_candidate_one_to_one(self):
        refs = [date(2023, 5, 10)]
        cands = [date(2023, 5, 8), date(2023, 5, 11)]  # +1d mais proximo que -2d
        res = match_events_one_to_one(refs, cands, tolerance_hours=48.0)
        assert res.tp == 1
        assert res.fp == 1
        assert res.matched_pairs == ((0, 1, 1.0),)

    def test_mills_severity_concordance(self):
        refs = ["heavy", "moderate", "light"]
        cands = ["moderate", "moderate", "heavy"]
        pairs = [(0, 0, 0.0), (1, 1, 0.25), (2, 2, -0.5)]
        conc = mills_severity_concordance(refs, cands, pairs)
        assert conc["n_matched"] == 3
        assert conc["exact_match_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert conc["underclassified_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert conc["overclassified_rate"] == pytest.approx(1 / 3, abs=1e-4)


class TestDailyCostLossModel:
    def test_perfect_and_fixed_strategies_hit_exact_theoretical_values(self):
        days = [date(2023, 5, 1) + timedelta(days=i) for i in range(100)]
        ref_alerts = set(days[:10])  # base_rate s = 0.10

        # Informacao perfeita -> V = 1.0 em todos os C/L
        perf = compute_daily_cost_loss(days, ref_alerts, ref_alerts, (0.05, 0.10, 0.20))
        assert perf["contingency"] == {"a_hit": 10, "b_false_alarm": 0, "c_miss": 0, "d_correct_neg": 90}
        assert perf["base_rate"] == pytest.approx(0.10)
        for key in ("0.05", "0.10", "0.20"):
            assert perf["by_ratio"][key]["relative_value"] == pytest.approx(1.0)

        # Nunca pulverizar -> E_cand = s = 0.10.
        # Em r=0.20, best_fixed = min(0.20, 0.10) = 0.10 (nunca) -> V = 0.0
        # Em r=0.05, best_fixed = min(0.05, 0.10) = 0.05 (sempre) -> V < 0 (pior que sempre pulverizar!)
        never = compute_daily_cost_loss(days, ref_alerts, set(), (0.05, 0.10, 0.20))
        assert never["by_ratio"]["0.20"]["relative_value"] == pytest.approx(0.0)
        assert never["by_ratio"]["0.10"]["relative_value"] == pytest.approx(0.0)
        assert never["by_ratio"]["0.05"]["relative_value"] < 0.0

        # Sempre pulverizar -> E_cand = r.
        # Em r=0.05, best_fixed = 0.05 (sempre) -> V = 0.0
        # Em r=0.20, best_fixed = 0.10 (nunca) -> V < 0 (pior que nunca pulverizar!)
        always = compute_daily_cost_loss(days, ref_alerts, set(days), (0.05, 0.10, 0.20))
        assert always["by_ratio"]["0.05"]["relative_value"] == pytest.approx(0.0)
        assert always["by_ratio"]["0.20"]["relative_value"] < 0.0


class TestBootstrapAndUsability:
    def test_polito_two_stations_omits_ci_and_four_stations_computes_ci(self):
        blocks_2 = [
            {"station_id": "s1", "tp": 8, "fp": 1, "fn": 2, "lags_days": [0.0, 0.5], "a_hit": 8, "b_false_alarm": 1, "c_miss": 2, "d_correct_neg": 89},
            {"station_id": "s2", "tp": 9, "fp": 2, "fn": 1, "lags_days": [0.0, 1.0], "a_hit": 9, "b_false_alarm": 2, "c_miss": 1, "d_correct_neg": 88},
        ]
        res2 = aggregate_station_metrics_with_bootstrap(blocks_2, n_boot=200, seed=42, compute_ci=True)
        assert res2["ci95_station_bootstrap"] is None  # n < 3 -> descritivo sem IC

        blocks_4 = blocks_2 + [
            {"station_id": "s3", "tp": 10, "fp": 1, "fn": 0, "lags_days": [0.0], "a_hit": 10, "b_false_alarm": 1, "c_miss": 0, "d_correct_neg": 89},
            {"station_id": "s4", "tp": 9, "fp": 1, "fn": 1, "lags_days": [0.5], "a_hit": 9, "b_false_alarm": 1, "c_miss": 1, "d_correct_neg": 89},
        ]
        res4 = aggregate_station_metrics_with_bootstrap(blocks_4, n_boot=500, seed=42, compute_ci=True)
        assert res4["ci95_station_bootstrap"] is not None
        lo, hi = res4["ci95_station_bootstrap"]["missed_rate"]
        assert 0.0 <= lo <= res4["point"]["missed_rate"] <= hi <= 1.0

    def test_usability_criteria_boundaries(self):
        # Passa nos 4 criterios
        ok = evaluate_usability(missed_rate=0.20, far=0.30, median_lag_days=1.0, missed_rate_ci95_hi=0.299)
        assert ok["usable"] is True

        # Falha se IC95 superior de alertas perdidos == 0.30 (precisa ser < 0.30)
        fail_ci = evaluate_usability(missed_rate=0.15, far=0.20, median_lag_days=0.5, missed_rate_ci95_hi=0.30)
        assert fail_ci["usable"] is False
        assert fail_ci["checks"]["missed_ci95_hi_lt_030"] is False

        # Falha se atraso mediano > 1.0 dia
        fail_lag = evaluate_usability(missed_rate=0.10, far=0.10, median_lag_days=1.25, missed_rate_ci95_hi=0.20)
        assert fail_lag["usable"] is False
        assert fail_lag["checks"]["median_lag_le_1d"] is False
