# -*- coding: utf-8 -*-
"""
Testes da Fase 3: decision_engine, db, simulator, app Flask e validação cruzada
Python vs R (AACPD até 1e-6). Rodam em CPU, sem rede, sem banco externo e sem GPU.
"""
from __future__ import annotations

import csv
import io
import json
import math
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as flask_app
import db
import decision_engine as de
import epidemiology_assimilation as ea
import simulator as sim

UTC = timezone.utc
LOCAL_TZ = de.LOCAL_TZ


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _make_epi_result(
    pot_id: str = "V11",
    disease: str = "pinta_preta",
    p_exceed: float = 0.10,
    regime_change: bool = False,
    fc_dsv: int = 2,
    fc_wallin: int = 0,
) -> dict:
    return {
        "schema_version": "1.0",
        "unit_id": pot_id,
        "disease": disease,
        "fitted_at": "2026-12-15T09:40:00-03:00",
        "model": "logistic",
        "n_obs": 6,
        "params": {
            "r": 0.25, "r_ci95": [0.15, 0.35], "r_unit": "por_dia_favoravel",
            "y0_pct": 0.3, "K_pct": 100.0, "r_prior": 0.18, "r_prior_sd_log": 0.7,
        },
        "fit": {"rmse_pct": 0.2, "chi2_red": 0.5, "aicc": {"logistic": 10.0},
                "forgetting": 0.97, "posterior_ess": 1500.0, "fitted_pct": [0.3, 1.0]},
        "innovation": {"predicted_pct": 1.0, "observed_pct": 1.2, "pred_sd_pct": 0.4,
                       "z": 0.5, "regime_change": regime_change},
        "tau": {"at_last_obs": 3.0, "calendar_days": 10.0, "weather_gap_hours": 0},
        "projection": [{"ts": "2026-12-22T09:40:00-03:00", "lead_h": 168, "tau": 5.0,
                        "y_median": 2.0, "y_lo95": 1.0, "y_hi95": 4.0}],
        "aacpd": {"unit": "pct_x_dia", "observed": 10.0, "projected_median": 15.0,
                  "projected_ci95": [10.0, 22.0], "total_median": 25.0,
                  "total_ci95": [20.0, 32.0], "relative_total": 0.02, "window_days": 17.0},
        "risk": {
            "wet_hours_7d": 20,
            "tomcast_dsv_7d": fc_dsv,
            "wallin_sv_7d": fc_wallin,
            "tau_gain_7d": 2.0,
            "p_exceed": {"threshold_pct": 5.0, "p": p_exceed},
        },
        "state": {"model": "logistic", "theta": [-1.4, -5.8], "mean": [-1.4, -5.8],
                  "cov": [[0.04, 0.0], [0.0, 0.04]], "k_floor": None,
                  "t0": "2026-12-01T12:00:00+00:00", "last_obs_ts": "2026-12-15T12:00:00+00:00"},
        "flags": [],
    }


def _dsv_rows(start: date, dsv_values: list[int], wallin_values: list[int] | None = None) -> list[dict]:
    wallin_values = wallin_values or [0] * len(dsv_values)
    return [
        {
            "station_id": "sj_vasos",
            "day": start + timedelta(days=i),
            "kind": "observed",
            "tomcast_dsv": d,
            "wallin_sv": w,
            "wet_hours": 8 if d > 0 else 0,
        }
        for i, (d, w) in enumerate(zip(dsv_values, wallin_values))
    ]


# --------------------------------------------------------------------------
# 1. Motor de decisão (`decision_engine.py`)
# --------------------------------------------------------------------------
def test_decision_control_pot_never_sprays():
    epi = _make_epi_result(pot_id="V05", disease="pinta_preta", p_exceed=0.99, regime_change=True)
    dsv = _dsv_rows(date(2026, 12, 1), [3] * 10)
    res = de.decide(epi, dsv, now="2026-12-15T09:41:00-03:00")
    assert res["schema_version"] == "1.0"
    assert res["pot_id"] == "V05"
    assert res["action"] == "none"
    assert res["reasons"] == ["control_pot"]
    assert set(res["inputs"].keys()) == {
        "dsv_since_last_spray", "wallin_sv_7d", "p_exceed", "days_since_last_spray", "regime_change"
    }


def test_decision_min_interval_blocks_spray():
    epi = _make_epi_result(pot_id="V11", disease="pinta_preta", p_exceed=0.95)
    dsv = _dsv_rows(date(2026, 12, 1), [4] * 15)
    res = de.decide(
        epi, dsv,
        last_spray={"applied_at": "2026-12-11T09:00:00-03:00"},
        now="2026-12-15T09:41:00-03:00",
    )
    assert res["action"] == "monitor"
    assert res["reasons"] == ["min_interval"]
    assert 4.0 <= res["inputs"]["days_since_last_spray"] < 7.0


def test_decision_tomcast_dsv_resets_after_spray_and_ignores_forecast():
    epi = _make_epi_result(pot_id="V12", disease="pinta_preta", p_exceed=0.10)
    # 20 DSV antes do spray em 06/12, apenas 6 DSV depois (07..15/12) + linha forecast alta
    dsv = _dsv_rows(date(2026, 12, 1), [4, 4, 4, 4, 4, 2, 1, 1, 1, 1, 1, 1, 0, 0, 0])
    dsv.append({"station_id": "sj_vasos", "day": date(2026, 12, 15), "kind": "forecast",
                "tomcast_dsv": 4, "wallin_sv": 4, "wet_hours": 24})
    res = de.decide(
        epi, dsv,
        last_spray="2026-12-06T08:00:00-03:00",
        now="2026-12-15T09:41:00-03:00",
    )
    assert res["inputs"]["dsv_since_last_spray"] == 6
    assert res["action"] == "none"
    assert res["reasons"] == []

    # Agora acumula >= 15 após o spray -> spray
    dsv2 = _dsv_rows(date(2026, 12, 1), [2] * 6 + [3] * 6)
    res2 = de.decide(
        epi, dsv2,
        last_spray="2026-12-06T08:00:00-03:00",
        now="2026-12-15T09:41:00-03:00",
    )
    assert res2["inputs"]["dsv_since_last_spray"] == 18
    assert res2["action"] == "spray"
    assert "dsv_since_last_spray>=15" in res2["reasons"]


def test_decision_requeima_wallin_7d_and_total():
    epi = _make_epi_result(pot_id="V14", disease="requeima", p_exceed=0.05)
    # 7 dias recentes somam 5 -> wallin_7d>=5
    dsv = _dsv_rows(date(2026, 12, 9), [0] * 7, [1, 1, 0, 1, 1, 0, 1])
    res = de.decide(epi, dsv, now="2026-12-15T10:00:00-03:00")
    assert res["action"] == "spray"
    assert "wallin_7d>=5" in res["reasons"]

    # Sem spray anterior, últimos 7d somam 3 (<5), mas total desde transplante >= 18
    dsv_long = _dsv_rows(date(2026, 11, 20), [0] * 26, [1] * 20 + [0, 0, 0, 1, 1, 1])
    res_total = de.decide(
        epi, dsv_long, last_spray=None,
        transplant_date=date(2026, 11, 20),
        now="2026-12-15T10:00:00-03:00",
    )
    assert res_total["action"] == "spray"
    assert "wallin_total>=18" in res_total["reasons"]

    # Se já houve spray anterior (há 10 dias), wallin_total>=18 não deve disparar
    res_after = de.decide(
        epi, dsv_long, last_spray="2026-12-05T08:00:00-03:00",
        transplant_date=date(2026, 11, 20),
        now="2026-12-15T10:00:00-03:00",
    )
    assert "wallin_total>=18" not in res_after["reasons"]
    assert res_after["action"] == "none"


def test_decision_p_exceed_and_monitor_rules():
    epi_p = _make_epi_result(pot_id="V15", disease="pinta_preta", p_exceed=0.50)
    res_p = de.decide(epi_p, [], now="2026-12-15T10:00:00-03:00")
    assert res_p["action"] == "spray"
    assert res_p["reasons"] == ["p_exceed>=0.5"]

    epi_mon = _make_epi_result(
        pot_id="V16", disease="pinta_preta", p_exceed=0.10, regime_change=True, fc_dsv=10
    )
    res_mon = de.decide(epi_mon, [], now="2026-12-15T10:00:00-03:00")
    assert res_mon["action"] == "monitor"
    assert res_mon["reasons"] == ["regime_change", "forecast_risk"]


def test_decision_rejects_naive_timestamp_and_invalid_pot():
    epi = _make_epi_result(pot_id="V11")
    with pytest.raises(ValueError):
        de.decide(epi, [], now="2026-12-15T10:00:00")
    with pytest.raises(ValueError):
        de.decide(_make_epi_result(pot_id="V25"), [], now="2026-12-15T10:00:00-03:00")


def test_compute_dsv_daily_rows_matches_assimilation():
    weather = sim.generate_synthetic_weather(datetime(2026, 12, 1, 0, tzinfo=UTC), days=5, seed=7)
    rows = de.compute_dsv_daily_rows(weather, station_id="sj_vasos", kind="observed")
    dsv_ref = ea.tomcast_dsv(weather)
    wal_ref = ea.wallin_severity(weather)
    assert len(rows) == len(dsv_ref)
    for r in rows:
        day_key = r["day"].isoformat()
        assert r["tomcast_dsv"] == int(dsv_ref[day_key])
        assert r["wallin_sv"] == int(wal_ref[day_key])


# --------------------------------------------------------------------------
# 2. Banco de dados (`db.py`)
# --------------------------------------------------------------------------
def test_db_validators_and_ddl_rules():
    assert db.validate_pot_id("V01") == "V01"
    assert db.validate_pot_id("V20") == "V20"
    assert db.validate_leaf_id("V11-F3") == "V11-F3"
    with pytest.raises(ValueError):
        db.validate_pot_id("V21")
    with pytest.raises(ValueError):
        db.validate_leaf_id("V11-F4")
    with pytest.raises(ValueError):
        db.ensure_utc("2026-12-01T09:30:00")   # sem fuso

    # Nenhuma instrução DELETE em db.py (SKILL.md seção 6)
    db_src = (ROOT / "db.py").read_text(encoding="utf-8").lower()
    assert "delete from" not in db_src
    for table in ("pots", "leaves", "video_assessments", "epi_fits", "spray_events", "dsv_daily", "decisions"):
        assert f"create table if not exists {table}" in db.APP_DDL.lower()
    assert "simulated" in db.APP_DDL.lower()


def test_db_init_and_idempotent_assessment_with_mock_conn():
    cur = MagicMock()
    cur.fetchone.side_effect = [(42,), None, (42,)]
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur

    vision_payload = {
        "leaf_id": "V11-F1",
        "captured_at": "2026-12-01T09:30:00-03:00",
        "video": {"sha256": "abc123"},
        "severity_pct": 2.5,
        "severity_sd_pct": 0.1,
        "necrosis_pct": 1.5,
        "chlorosis_pct": 1.0,
        "leaf_area_cm2": 40.0,
        "lesion_area_mm2": 100.0,
        "quality": {"ok": True, "flags": []},
    }
    aid1, created1 = db.insert_video_assessment(conn, vision_payload, "data/videos/2026-12-01/v.mp4")
    aid2, created2 = db.insert_video_assessment(conn, vision_payload, "data/videos/2026-12-01/v.mp4")
    assert (aid1, created1) == (42, True)
    assert (aid2, created2) == (42, False)


# --------------------------------------------------------------------------
# 3. Simulador de circuito fechado (`simulator.py`)
# --------------------------------------------------------------------------
def test_simulator_closed_loop_pinta_preta_controls_disease(tmp_path):
    # Clima quente e úmido favorável à pinta-preta em São José/SC
    weather = sim.generate_synthetic_weather(
        datetime(2025, 11, 1, 0, tzinfo=UTC),
        days=56, seed=42, mean_temp_c=25.0, mean_rh_pct=86.0, rain_prob=0.12,
    )
    cfg = sim.SimulationConfig(
        disease="pinta_preta",
        season_days=36,
        eval_cadence_days=(3,),
        seed=42,
        n_draws=400,
    )
    res = sim.run_simulation(weather, cfg)
    assert res["simulated"] is True
    assert len(res["pots"]) == 20
    assert all(p["simulated"] is True for p in res["pots"])

    summary = res["summary_by_treatment"]
    assert summary["testemunha"]["sprays_total"] == 0
    assert summary["dss"]["sprays_total"] > 0
    # Critério de aceite do BRIEFING.md seção 7: AACPD do grupo DSS abaixo da testemunha
    assert summary["dss"]["aacpd_mean"] < summary["testemunha"]["aacpd_mean"]

    # Exportação no formato exato do SKILL.md seção 9
    csv_path = tmp_path / "aacpd_por_vaso.csv"
    series_path = tmp_path / "series_por_vaso.csv"
    sim.export_simulation_aacpd_csv(res, csv_path, series_output_path=series_path)
    with open(csv_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames) == db.AACPD_CSV_COLUMNS
        rows = list(reader)
    assert len(rows) == 20

    # Validação cruzada Python vs R até 1e-6 (se Rscript disponível na máquina)
    rscript = shutil.which("Rscript") or (
        r"C:\Program Files\R\R-4.6.1\bin\Rscript.exe"
        if Path(r"C:\Program Files\R\R-4.6.1\bin\Rscript.exe").exists()
        else None
    )
    if rscript:
        proc = subprocess.run(
            [rscript, str(ROOT / "r" / "aacpd_validacao.R"), str(csv_path), str(series_path)],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, f"R falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert "AACPD Python e R coincidem" in proc.stdout


def test_simulator_compare_three_strategies_requeima():
    weather = sim.generate_synthetic_weather(
        datetime(2025, 6, 1, 0, tzinfo=UTC),
        days=45, seed=99, mean_temp_c=18.5, mean_rh_pct=88.0, rain_prob=0.15,
    )
    cfg = sim.SimulationConfig(
        disease="requeima",
        season_days=28,
        eval_cadence_days=(3, 4),
        seed=99,
        n_draws=300,
    )
    cmp_res = sim.compare_strategies(weather, cfg)
    st = cmp_res["strategies"]
    assert set(st.keys()) == {"testemunha", "calendario_semanal", "dss"}
    assert st["testemunha"]["sprays_total"] == 0
    assert st["dss"]["aacpd_mean"] < st["testemunha"]["aacpd_mean"]
    assert st["calendario_semanal"]["aacpd_mean"] < st["testemunha"]["aacpd_mean"]


def test_simulator_loads_epagri_csv(tmp_path):
    csv_file = tmp_path / "epagri.csv"
    csv_file.write_text(
        "Estacao: Itacorubi (Florianopolis)\n"
        "DataHorario,TempArInst(C),UmidRelMedia(%),Precipitacao(mm),Vel.MediaVento(m/s),\n"
        "01/12/2026 09:00:00,23.5,82.0,0.0,2.1,\n"
        "01/12/2026 10:00:00,25.0,75.0,0.4,2.5,\n"
        "01/12/2026 11:00:00,9999.9,9999.9,0.0,1.0,\n",
        encoding="utf-8",
    )
    rows = sim.load_weather_from_csv(csv_file)
    assert len(rows) == 2
    assert rows[0]["ts"].endswith("+00:00")
    assert rows[0]["temp_c"] == 23.5


# --------------------------------------------------------------------------
# 4. Calibração do IC 95 % do modelo epidemiológico (BRIEFING.md Fase 2.4)
# --------------------------------------------------------------------------
def test_epidemiology_ci95_coverage_on_simulated_epidemics():
    """
    Confere que o intervalo de 95 % projetado em 7 dias cobre a severidade real
    na faixa calibrada em epidemias simuladas.
    """
    weather = sim.generate_synthetic_weather(
        datetime(2026, 12, 1, 0, tzinfo=UTC), days=30, seed=123, mean_temp_c=23.0, mean_rh_pct=82.0
    )
    wdf = ea.weather_frame(weather)
    cfg = ea.AssimilationConfig(n_draws=1000, fc_sigma0=0.0, fc_sigma_per_day=0.0)
    t0 = datetime(2026, 12, 1, 12, tzinfo=UTC)
    clock = ea.build_clock(wdf, t0, t0 + timedelta(days=25), "pinta_preta", cfg)
    cut = t0 + timedelta(days=14)
    w_obs = [w for w in weather if datetime.fromisoformat(w["ts"]) <= cut]
    w_fc = [w for w in weather if datetime.fromisoformat(w["ts"]) > cut]

    rng = np.random.default_rng(2026)
    covered = 0
    n_trials = 25
    for i in range(n_trials):
        r_true = float(0.18 * math.exp(rng.normal(0.0, 0.35)))
        y0_true = float(0.35 * math.exp(rng.normal(0.0, 0.30)))
        obs = []
        for day in range(0, 15, 2):
            ts = t0 + timedelta(days=day)
            truth = float(ea.curve("logistic", clock.tau(ts)[0], r_true, y0_true, 100.0))
            sd = math.sqrt(0.30 ** 2 + (0.10 * truth) ** 2)
            obs.append({
                "ts": ts.isoformat(),
                "severity_pct": float(np.clip(truth + rng.normal(0.0, sd), 0.0, 100.0)),
                "severity_sd_pct": 0.0,
            })
        res = ea.assimilate(
            unit_id="V11", disease="pinta_preta", observations=obs,
            weather_observed=w_obs, weather_forecast=w_fc,
            config=ea.AssimilationConfig(n_draws=1000, seed=100 + i),
        )
        truth_7d = float(ea.curve("logistic", clock.tau(cut + timedelta(days=7))[0], r_true, y0_true, 100.0))
        last_pt = res["projection"][-1]
        if last_pt["y_lo95"] <= truth_7d <= last_pt["y_hi95"]:
            covered += 1

    coverage_rate = covered / n_trials
    assert 0.80 <= coverage_rate <= 1.0, f"cobertura fora do esperado: {coverage_rate:.2f}"


# --------------------------------------------------------------------------
# 5. API Flask (`app.py`) — todas as 7 rotas do SKILL.md seção 5.5
# --------------------------------------------------------------------------
class _FakeVisionPipeline:
    def __init__(self, quality_ok: bool = True):
        self.cfg = flask_app.vp.PipelineConfig(weights_a=None, weights_b=None)
        self.quality_ok = quality_ok
        self.calls = 0

    def process(self, video_path: str, leaf_id=None, captured_at=None, debug_dir=None) -> dict:
        self.calls += 1
        data = Path(video_path).read_bytes()
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        pot_id = leaf_id.split("-")[0]
        return {
            "schema_version": "1.0",
            "leaf_id": leaf_id,
            "pot_id": pot_id,
            "captured_at": captured_at,
            "video": {"file": Path(video_path).name, "sha256": sha, "n_frames": 120,
                      "fps": 30.0, "width": 1920, "height": 1080},
            "severity_pct": 4.2,
            "severity_sd_pct": 0.15,
            "necrosis_pct": 2.6,
            "chlorosis_pct": 1.6,
            "leaf_area_cm2": 41.0,
            "lesion_area_mm2": 172.2,
            "necrosis_area_mm2": 106.6,
            "chlorosis_area_mm2": 65.6,
            "calibration": {"px_per_cm": 90.0, "ref_square_side_px": 180.0,
                            "ref_square_side_cm": 2.0, "squareness": 1.0, "ok": True},
            "aggregation": {"method": "consensus", "n_keyframes": 4, "n_valid": 4,
                            "n_aligned": 4, "reference_frame": 0},
            "keyframe_selection": {"sharpness_p90": 95.0, "n_blurry": 5, "n_duplicates_dropped": 0},
            "method": {"weights_a": "stage_a_leaf.pt", "weights_b": "stage_b_lesion.pt",
                       "device": "cpu", "half": False, "stage_a": "yolo", "stage_b": "yolo"},
            "keyframes": [],
            "quality": {"ok": self.quality_ok, "flags": [] if self.quality_ok else ["few_keyframes"]},
            "processing_ms": 120,
        }


def test_flask_api_all_routes_end_to_end(tmp_path, monkeypatch):
    store = {
        "assessments": {},     # sha256 -> row
        "assessments_list": [],
        "epi_fits": [],
        "decisions": [],
        "sprays": [],
        "dsv_daily": [],
        "weather_obs": sim.generate_synthetic_weather(datetime(2026, 12, 1, 0, tzinfo=UTC), days=10, seed=5),
        "weather_fc": sim.generate_synthetic_weather(datetime(2026, 12, 11, 0, tzinfo=UTC), days=7, seed=6),
    }

    class _DummyConn:
        def close(self):
            return None

    monkeypatch.setattr(db, "check_health", lambda conn: True)
    monkeypatch.setattr(db, "get_assessment_by_sha256", lambda conn, sha: store["assessments"].get(sha))

    def _ins_assess(conn, vision_res, video_path, simulated=False):
        sha = vision_res["video"]["sha256"]
        if sha in store["assessments"]:
            return store["assessments"][sha]["assessment_id"], False
        aid = len(store["assessments_list"]) + 1
        row = {
            "assessment_id": aid,
            "leaf_id": vision_res["leaf_id"],
            "pot_id": vision_res["pot_id"],
            "ts": vision_res["captured_at"],
            "severity_pct": vision_res["severity_pct"],
            "severity_sd_pct": vision_res["severity_sd_pct"],
            "accepted": bool(vision_res["quality"]["ok"]),
            "result": vision_res,
        }
        store["assessments"][sha] = row
        store["assessments_list"].append(row)
        return aid, True

    monkeypatch.setattr(db, "insert_video_assessment", _ins_assess)
    monkeypatch.setattr(
        db, "get_accepted_assessments_for_pot",
        lambda conn, pot_id, disease=None, simulated=False: [
            r for r in store["assessments_list"] if r["pot_id"] == pot_id and r["accepted"]
        ],
    )
    monkeypatch.setattr(
        db, "get_weather_hourly",
        lambda conn, station_id="sj_vasos", kind="observed", start=None, end=None: (
            store["weather_obs"] if kind == "observed" else store["weather_fc"]
        ),
    )
    monkeypatch.setattr(
        db, "get_weather_summary",
        lambda conn, station_id="sj_vasos", now=None: {
            "station_id": station_id,
            "observed_72h_coverage": 1.0,
            "forecast_168h_coverage": 1.0,
            "last_observed": store["weather_obs"][-1],
        },
    )
    monkeypatch.setattr(db, "get_dsv_daily", lambda conn, station_id="sj_vasos", kind="observed": store["dsv_daily"])
    monkeypatch.setattr(db, "upsert_dsv_daily", lambda conn, rows: store["dsv_daily"].extend(rows) or len(rows))
    monkeypatch.setattr(
        db, "insert_epi_fit",
        lambda conn, fit_res, simulated=False: store["epi_fits"].append({"fit_id": len(store["epi_fits"]) + 1,
                                                                         "pot_id": fit_res["unit_id"],
                                                                         "disease": fit_res["disease"],
                                                                         "state": fit_res["state"],
                                                                         "result": fit_res}) or len(store["epi_fits"]),
    )
    monkeypatch.setattr(
        db, "get_latest_epi_fit",
        lambda conn, pot_id, disease, simulated=False: next(
            (f for f in reversed(store["epi_fits"]) if f["pot_id"] == pot_id and f["disease"] == disease), None
        ),
    )
    monkeypatch.setattr(
        db, "insert_decision",
        lambda conn, dec_res, simulated=False: store["decisions"].append({"decision_id": len(store["decisions"]) + 1,
                                                                          "pot_id": dec_res["pot_id"],
                                                                          "disease": dec_res["disease"],
                                                                          "result": dec_res}) or len(store["decisions"]),
    )
    monkeypatch.setattr(
        db, "get_latest_decision",
        lambda conn, pot_id, disease, simulated=False: next(
            (d for d in reversed(store["decisions"]) if d["pot_id"] == pot_id and d["disease"] == disease), None
        ),
    )
    monkeypatch.setattr(
        db, "insert_spray_event",
        lambda conn, pot_id, applied_at, product, dose=None, notes=None, simulated=False: (
            store["sprays"].append({"spray_id": len(store["sprays"]) + 1, "pot_id": pot_id,
                                    "applied_at": db.ensure_utc(applied_at).isoformat(),
                                    "product": product, "dose": dose, "notes": notes})
            or len(store["sprays"])
        ),
    )
    monkeypatch.setattr(
        db, "get_spray_events",
        lambda conn, pot_id, simulated=False: [s for s in store["sprays"] if s["pot_id"] == pot_id],
    )
    monkeypatch.setattr(
        db, "get_last_spray_event",
        lambda conn, pot_id, simulated=False: next(
            (s for s in reversed(store["sprays"]) if s["pot_id"] == pot_id), None
        ),
    )

    fake_vision = _FakeVisionPipeline(quality_ok=True)
    application = flask_app.create_app(
        db_conn_factory=_DummyConn,
        vision_pipeline=fake_vision,
        data_dir=tmp_path / "data",
    )
    client = application.test_client()

    # 1. GET /api/v1/health
    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert set(r_health.get_json().keys()) == {"db", "gpu", "weights"}
    assert r_health.get_json()["db"] is True

    # 2. POST /api/v1/assessments (erros de validação)
    r_bad = client.post("/api/v1/assessments", data={
        "leaf_id": "INVALID", "captured_at": "2026-12-01T09:30:00-03:00",
        "video": (io.BytesIO(b"fake-video-1"), "v.mp4"),
    }, content_type="multipart/form-data")
    assert r_bad.status_code == 400
    assert r_bad.get_json()["error"]["code"] == "invalid_leaf_id"

    r_naive = client.post("/api/v1/assessments", data={
        "leaf_id": "V11-F1", "captured_at": "2026-12-01T09:30:00",
        "video": (io.BytesIO(b"fake-video-1"), "v.mp4"),
    }, content_type="multipart/form-data")
    assert r_naive.status_code == 400
    assert r_naive.get_json()["error"]["code"] == "invalid_timestamp"

    # 3. POST /api/v1/assessments (201, arquivo salvo em data/videos/AAAA-MM-DD/, e deduplicação 200)
    r_ok = client.post("/api/v1/assessments", data={
        "leaf_id": "V11-F1", "captured_at": "2026-12-01T09:30:00-03:00",
        "video": (io.BytesIO(b"fake-video-bytes-1"), "V11-F1_20261201T0930.mp4"),
    }, content_type="multipart/form-data")
    assert r_ok.status_code == 201
    assert r_ok.get_json()["assessment_id"] == 1
    assert (tmp_path / "data" / "videos" / "2026-12-01" / "V11-F1_20261201T0930.mp4").is_file()

    # Reenvio do mesmo vídeo -> 200 com mesmo assessment_id sem reprocessar
    r_dup = client.post("/api/v1/assessments", data={
        "leaf_id": "V11-F1", "captured_at": "2026-12-01T09:30:00-03:00",
        "video": (io.BytesIO(b"fake-video-bytes-1"), "V11-F1_20261201T0930.mp4"),
    }, content_type="multipart/form-data")
    assert r_dup.status_code == 200
    assert r_dup.get_json()["assessment_id"] == 1
    assert fake_vision.calls == 1

    # Vídeo com quality.ok == False -> 422 com mesmo formato de corpo
    fake_vision.quality_ok = False
    r_bad_q = client.post("/api/v1/assessments", data={
        "leaf_id": "V11-F2", "captured_at": "2026-12-01T09:35:00-03:00",
        "video": (io.BytesIO(b"fake-video-bytes-bad"), "V11-F2_20261201T0935.mp4"),
    }, content_type="multipart/form-data")
    assert r_bad_q.status_code == 422
    assert r_bad_q.get_json()["vision"]["quality"]["ok"] is False

    # Segunda avaliação aceita em outro dia
    fake_vision.quality_ok = True
    r_ok2 = client.post("/api/v1/assessments", data={
        "leaf_id": "V11-F1", "captured_at": "2026-12-04T09:30:00-03:00",
        "video": (io.BytesIO(b"fake-video-bytes-2"), "V11-F1_20261204T0930.mp4"),
    }, content_type="multipart/form-data")
    assert r_ok2.status_code == 201

    # 4. POST /api/v1/pots/V11/assimilate?disease=pinta_preta
    r_assim = client.post("/api/v1/pots/V11/assimilate?disease=pinta_preta")
    assert r_assim.status_code == 200
    fit_json = r_assim.get_json()
    assert fit_json["unit_id"] == "V11"
    assert fit_json["n_obs"] == 2

    # 5. GET /api/v1/pots/V11/projection?disease=pinta_preta
    r_proj = client.get("/api/v1/pots/V11/projection?disease=pinta_preta")
    assert r_proj.status_code == 200
    assert r_proj.get_json()["unit_id"] == "V11"

    # 6. GET /api/v1/pots/V11/decision?disease=pinta_preta
    r_dec = client.get("/api/v1/pots/V11/decision?disease=pinta_preta")
    assert r_dec.status_code == 200
    dec_json = r_dec.get_json()
    assert dec_json["pot_id"] == "V11"
    assert dec_json["action"] in ("spray", "monitor", "none")

    # 7. POST /api/v1/sprays
    r_spray = client.post("/api/v1/sprays", json={
        "pot_id": "V11",
        "applied_at": "2026-12-05T08:00:00-03:00",
        "product": "Mancozebe",
        "dose": "2 g/L",
        "notes": "receituario 001",
    })
    assert r_spray.status_code == 201
    assert r_spray.get_json()["spray_id"] == 1

    # 8. GET /api/v1/weather/summary
    r_ws = client.get("/api/v1/weather/summary")
    assert r_ws.status_code == 200
    assert r_ws.get_json()["observed_72h_coverage"] == 1.0
