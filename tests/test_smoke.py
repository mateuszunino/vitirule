# -*- coding: utf-8 -*-
"""
Testes de fumaça dos três módulos. Rodam em CPU, sem rede, sem banco e sem
pesos treinados. Uso: python -m pytest tests/ -q
"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import epidemiology_assimilation as ea
import vision_pipeline as vp
import weather_collector as wc

UTC = timezone.utc
START = datetime(2026, 12, 1, 12, tzinfo=UTC)


# ------------------------------------------------------------------ clima sintético
def synthetic_weather(days, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for h in range(1, 24 * days + 1):
        ts = START + timedelta(hours=h)
        local_hour = (ts.hour - 3) % 24
        wave = math.sin((local_hour - 9) / 24 * 2 * math.pi)
        rows.append({"ts": ts.isoformat(), "temp_c": 22 + 5 * wave + rng.normal(0, 0.5),
                     "rh_pct": min(78 - 16 * wave + rng.normal(0, 3), 100.0), "precip_mm": 0.0})
    return rows


# ------------------------------------------------------------------ assimilação
@pytest.mark.parametrize("temp,hours,expected", [
    (15, 6, 0), (15, 7, 1), (15, 16, 2), (15, 21, 3), (15, 24, 3),
    (19, 3, 0), (19, 4, 1), (19, 9, 2), (19, 16, 3), (19, 23, 4),
    (23, 2, 0), (23, 3, 1), (23, 6, 2), (23, 13, 3), (23, 21, 4),
    (27, 4, 1), (27, 23, 4), (12, 24, 0), (30, 24, 0)])
def test_tomcast_table(temp, hours, expected):
    assert ea._lookup(ea.TOMCAST_TABLE, temp, hours) == expected


@pytest.mark.parametrize("temp,hours,expected", [
    (9, 15, 0), (9, 16, 1), (9, 19, 2), (9, 22, 3), (9, 24, 3),
    (13, 12, 0), (13, 13, 1), (13, 16, 2), (13, 19, 3), (13, 22, 4),
    (20, 9, 0), (20, 10, 1), (20, 13, 2), (20, 16, 3), (20, 19, 4), (28, 24, 0)])
def test_wallin_table(temp, hours, expected):
    assert ea._lookup(ea.WALLIN_TABLE, temp, hours) == expected


def test_aacpd_matches_manual_trapezoid():
    times = [(START + timedelta(days=d)).isoformat() for d in (0, 2, 5, 7)]
    assert ea.aacpd(times, [0, 2, 6, 10]) == pytest.approx(30.0, abs=1e-9)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        ea.assimilate("V01", "pinta_preta", [{"ts": "2026-12-01T09:00:00", "severity_pct": 1.0}])


def test_assimilation_recovers_rate_and_covers_truth():
    weather = synthetic_weather(22)
    cfg = ea.AssimilationConfig(n_draws=1500)
    clock = ea.build_clock(ea.weather_frame(weather), START, START + timedelta(days=21), "pinta_preta", cfg)
    r_true, y0_true = 0.50, 1.0
    rng = np.random.default_rng(2)
    obs = []
    for day in (0, 2, 4, 7, 9, 11, 14):
        ts = START + timedelta(days=day)
        truth = float(ea.curve("logistic", clock.tau(ts)[0], r_true, y0_true, 100.0))
        obs.append({"ts": ts.isoformat(), "severity_pct": max(truth * (1 + rng.normal(0, 0.05)), 0.0),
                    "severity_sd_pct": 0.1})
    cut = START + timedelta(days=14)
    out = ea.assimilate("V01", "pinta_preta", obs,
                        [w for w in weather if datetime.fromisoformat(w["ts"]) <= cut],
                        [w for w in weather if datetime.fromisoformat(w["ts"]) > cut], config=cfg)
    json.dumps(out)
    assert out["params"]["r_ci95"][0] <= r_true <= out["params"]["r_ci95"][1]
    truth_7d = float(ea.curve("logistic", clock.tau(START + timedelta(days=21))[0], r_true, y0_true, 100.0))
    last = out["projection"][-1]
    assert last["lead_h"] == 168 and len(out["projection"]) == 29
    assert last["y_lo95"] <= truth_7d <= last["y_hi95"]
    assert out["aacpd"]["total_ci95"][0] <= out["aacpd"]["total_median"] <= out["aacpd"]["total_ci95"][1]
    assert set(out) >= {"schema_version", "unit_id", "disease", "model", "params", "fit", "innovation",
                        "tau", "projection", "aacpd", "risk", "state", "flags"}


def test_single_observation_and_zeros_do_not_crash():
    one = ea.assimilate("V02", "requeima", [{"ts": START.isoformat(), "severity_pct": 1.2}])
    assert "prior_dominated" in one["flags"] and one["params"]["r"] == pytest.approx(0.35, rel=1e-6)
    zeros = ea.assimilate("V03", "pinta_preta",
                          [{"ts": (START + timedelta(days=d)).isoformat(), "severity_pct": 0.0} for d in (0, 2, 4)],
                          synthetic_weather(12))
    assert "pre_symptomatic" in zeros["flags"]
    assert 0.0 <= zeros["projection"][-1]["y_lo95"] <= zeros["projection"][-1]["y_hi95"] <= 100.0


def test_jump_triggers_regime_change():
    state, obs, out = None, [], None
    weather = synthetic_weather(25)
    for day, value in zip((0, 3, 6, 9, 12, 15), (0.5, 0.7, 1.0, 1.4, 1.9, 14.0)):
        obs.append({"ts": (START + timedelta(days=day)).isoformat(), "severity_pct": value, "severity_sd_pct": 0.1})
        out = ea.assimilate("V04", "pinta_preta", obs, weather, prev_state=state,
                            config=ea.AssimilationConfig(n_draws=1500))
        state = out["state"]
    assert out["innovation"]["regime_change"] and "regime_change" in out["flags"]


# ------------------------------------------------------------------ clima
class _Resp:
    def __init__(self, code=200, payload=None):
        self.status_code, self._payload, self.headers = code, payload, {}
        self.content = b"" if payload is None else json.dumps(payload).encode()

    def json(self):
        return self._payload


class _Session:
    def __init__(self, inmet, open_meteo):
        self.inmet, self.open_meteo, self.headers, self.calls = inmet, open_meteo, {}, 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        queue = self.inmet if "inmet" in url else self.open_meteo
        return queue.pop(0) if len(queue) > 1 else queue[0]


NOW = datetime(2026, 12, 10, 12, 20, tzinfo=UTC)


def _inmet_rows():
    rows = []
    for h in range(80, -1, -1):
        ts = NOW.replace(minute=0) - timedelta(hours=h)
        local_hour = (ts.hour - 3) % 24
        rows.append({"DT_MEDICAO": ts.strftime("%Y-%m-%d"), "HR_MEDICAO": ts.strftime("%H%M"),
                     "TEM_INS": f"{22 + 6 * math.cos((local_hour - 15) / 24 * 2 * math.pi):.1f}",
                     "UMD_INS": "88", "CHUVA": "0", "PTO_INS": "18", "VEN_VEL": "2", "RAD_GLO": "1800"})
    return rows


def _open_meteo_payload():
    start = (NOW.replace(minute=0) - timedelta(days=4)).replace(hour=0)
    times = [start + timedelta(hours=h) for h in range(24 * 13)]
    n = len(times)
    return {"hourly": {"time": [int(t.timestamp()) for t in times], "temperature_2m": [21.0] * n,
                       "relative_humidity_2m": [80] * n, "dew_point_2m": [17.0] * n,
                       "precipitation": [0.0] * n, "wind_speed_10m": [3.0] * n,
                       "shortwave_radiation": [200.0] * n}}


def _settings(**kw):
    return wc.Settings(http_backoff_base=0.001, http_backoff_cap=0.002, **kw)


def test_collector_windows_and_units():
    result = wc.collect(_settings(), now=NOW, session=_Session([_Resp(200, _inmet_rows())], [_Resp(200, _open_meteo_payload())]))
    assert result.status in ("ok", "ok_with_fallback")
    assert len(result.observed) == 72 and len(result.forecast) == 168
    assert result.observed[-1].ts == NOW.replace(minute=0)
    assert result.forecast[0].ts == NOW.replace(minute=0) + timedelta(hours=1)
    assert all(r.ts.tzinfo is not None and r.ts.minute == 0 for r in result.observed + result.forecast)
    inmet = next(r for r in result.observed if r.source == "inmet")
    assert inmet.rad_wm2 == pytest.approx(500.0) and inmet.leaf_wet(85.0) is True


def test_collector_retries_then_falls_back():
    session = _Session([_Resp(503), _Resp(503), _Resp(200, _inmet_rows())], [_Resp(200, _open_meteo_payload())])
    assert wc.collect(_settings(), now=NOW, session=session).sources["observed"]["inmet"] == 72
    down = wc.collect(_settings(http_attempts=2), now=NOW,
                      session=_Session([_Resp(500)], [_Resp(200, _open_meteo_payload())]))
    assert down.sources["observed"] == {"open_meteo": 72} and all(not r.is_measured for r in down.observed)


def test_epagri_csv_local_time_and_missing_code(tmp_path):
    lines = ["1006,Florianopolis - Itacorubi,Florianopolis,-27,58,-48,50,5,",
             "Codigo,DataHorario,TempArInst(C),TempMin(C),TempMax(C),Vel.MediaVento(m/s),Dir.MediaVento(Graus),"
             "VentoMax(m/s),PressaoAtm(mB),UmidRelMedia(%),Precipitacao(mm)",
             "1006,10/12/2026 08:00:00,21.5,21.0,22.0,9999.9,9999.9,9999.9,9999.9,91.5,0,"]
    path = tmp_path / "dados_download1006.csv"
    path.write_text("\n".join(lines), encoding="utf-8")
    record = wc.EpagriProvider(_settings(), None).parse_csv(path)[0]
    assert record.ts == datetime(2026, 12, 10, 11, 0, tzinfo=UTC)      # 08 h local = 11 h UTC
    assert record.temp_c == 21.5 and record.rh_pct == 91.5 and record.wind_ms is None


def test_token_never_leaks():
    result = wc.collect(_settings(inmet_token="SEGREDO"), now=NOW,
                        session=_Session([_Resp(401)], [_Resp(200, _open_meteo_payload())]))
    assert not any("SEGREDO" in message for message in result.errors)


# ------------------------------------------------------------------ visão
def _synthetic_video(path, px_per_cm=45.0):
    w, h = 960, 540
    scene = np.full((h, w, 3), (225, 105, 65), np.uint8)
    leaf = np.zeros((h, w), np.uint8)
    cv2.ellipse(leaf, (430, 270), (210, 125), 0, 0, 360, 1, -1)
    rng = np.random.default_rng(0)
    texture = cv2.GaussianBlur(rng.normal(0, 12, (h, w)).astype(np.float32), (0, 0), 2)
    green = np.clip(np.array([45, 125, 55], np.float32) + texture[..., None], 0, 255).astype(np.uint8)
    scene[leaf > 0] = green[leaf > 0]
    necrosis = np.zeros((h, w), np.uint8)
    for x, y, r in ((380, 240, 22), (500, 300, 16)):
        cv2.circle(necrosis, (x, y), r, 1, -1)
    scene[necrosis > 0] = (45, 72, 112)
    side = int(2 * px_per_cm)
    cv2.rectangle(scene, (780, 60), (780 + side, 60 + side), (245, 245, 245), -1)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    for i in range(60):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 1.5 * math.sin(i / 12), 1.0)
        M[:, 2] += (8 * math.sin(i / 9), 5 * math.cos(i / 7))
        frame = cv2.warpAffine(scene, M, (w, h), borderValue=(225, 105, 65))
        if 20 <= i < 30:
            kernel = np.zeros((15, 15), np.float32)
            kernel[7, :] = 1 / 15
            frame = cv2.filter2D(frame, -1, kernel)
        writer.write(frame)
    writer.release()
    return {"necrosis_pct": 100.0 * necrosis.sum() / leaf.sum(), "leaf_cm2": leaf.sum() / px_per_cm ** 2}


def test_vision_classical_path_on_synthetic_video(tmp_path):
    video = tmp_path / "V11-F2_20261201T0930.mp4"
    truth = _synthetic_video(video)
    cfg = vp.PipelineConfig(weights_a=None, weights_b=None)
    out = vp.VisionPipeline(cfg).process(str(video), captured_at="2026-12-01T09:30:00-03:00")
    json.dumps(out)
    assert out["leaf_id"] == "V11-F2" and out["pot_id"] == "V11"
    assert out["necrosis_pct"] == pytest.approx(truth["necrosis_pct"], abs=0.3)
    assert out["leaf_area_cm2"] == pytest.approx(truth["leaf_cm2"], rel=0.03)
    assert out["calibration"]["px_per_cm"] == pytest.approx(45.0, rel=0.02)
    assert out["severity_pct"] == pytest.approx(out["necrosis_pct"] + out["chlorosis_pct"], abs=1e-3)
    assert not any(20 <= k["frame_index"] < 30 for k in out["keyframes"])        # frames borrados fora
    assert "classical_fallback_stage_a" in out["quality"]["flags"] and out["quality"]["ok"] is False


def test_consensus_drops_single_frame_artifact():
    leaf = np.zeros((120, 120), np.uint8)
    leaf[10:110, 10:110] = 1
    lesion = np.zeros_like(leaf)
    lesion[30:50, 30:50] = 1
    glare = lesion.copy()
    glare[70:100, 70:100] = 1
    make = lambda n: vp.FrameAnalysis(vp.Keyframe(0, 1.0, None), leaf=leaf.copy(), necrosis=n.copy(),
                                      chlorosis=np.zeros_like(leaf))
    frames = [make(lesion), make(glare), make(lesion)]
    for f in frames[1:]:
        f.aligned, f._warped = True, (f.leaf, f.necrosis, f.chlorosis)
    _, necrosis, _, used = vp.consensus_masks(frames, frames[0])
    assert used == 3 and int(necrosis.sum()) == 400
