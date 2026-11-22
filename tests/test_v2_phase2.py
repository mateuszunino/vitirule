"""
Testes unitarios da Fase 2 e das emendas pre-Fase 3:
- Emenda 1 (QC): mascaramento de lacunas + periodo de aquecimento por regra
- Emenda 2 (Regra 3-10): temperatura minima diaria (`daily_min`) vs media diaria (`daily_mean`)
- Estimadores de molhamento foliar (`rh90_rain`, `dpd_hysteresis` Gillespie 1993, `cart_kim2002`)
- Coletores de fontes: NASA POWER exigindo `time-standard=UTC` explicitamente,
  conversao de radiacao MJ/h -> W/m2, Open-Meteo parsing/cache e distancia/altitude de grade.
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vitirule_v2.lwd import (
    PRIMARY_LWD_METHOD,
    apply_lwd_estimator,
    estimate_lwd_flags,
    magnus_dewpoint_c,
    wind_10m_to_2m_ms,
)
from vitirule_v2.qc import (
    compute_masked_hours_for_rule,
    evaluate_station_season_qc,
    event_touches_masked_hours,
    rule_warmup_hours,
)
from vitirule_v2.rules import HourlyRecord, detect_rule_3_10
from vitirule_v2.sources.grid_metadata import build_station_grid_match, haversine_km, nearest_merra2_center
from vitirule_v2.sources.nasa_power import (
    MJ_PER_HR_TO_WM2,
    build_nasa_power_params,
    fetch_nasa_power_hourly,
    parse_nasa_power_payload,
)
from vitirule_v2.sources.open_meteo import parse_open_meteo_hourly_payload

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


# ==========================================================================
# 1. Emenda 1: QC com mascaramento e periodo de aquecimento por regra
# ==========================================================================
class TestQCAmendmentMasking:
    def _clean_season(self, start_d: date, end_d: date) -> list[HourlyRecord]:
        n_days = (end_d - start_d).days + 1
        out: list[HourlyRecord] = []
        for d_idx in range(n_days):
            cur = start_d + timedelta(days=d_idx)
            for hr in range(24):
                ts = datetime(cur.year, cur.month, cur.day, hr, 0, tzinfo=UTC)
                is_night = hr < 6
                out.append(
                    HourlyRecord(
                        ts=ts,
                        temp_c=18.0 if is_night else 24.0,
                        rh_pct=92.0 if is_night else 50.0,
                        precip_mm=2.0 if (d_idx % 7 == 0 and hr == 2) else 0.0,
                        wet=is_night,
                    )
                )
        return out

    def test_rule_warmup_hours_derived_from_params(self):
        w = rule_warmup_hours()
        assert w["rule_3_10"] == 48
        assert w["mills_revised"] == 9       # 8 h interrupcao seca + 1 h lookback de chuva
        assert w["tomcast"] == 15 * 24       # 15 DSV a 1 DSV/dia = 360 h
        assert w["goidanich"] == 24 * 24     # ceil(100 / (5.0 * 0.85)) = 24 dias = 576 h

    def test_amended_qc_passes_30h_gap_when_coverage_ge_95_and_masks_warmup(self):
        recs = self._clean_season(date(2023, 5, 1), date(2023, 9, 30))
        # Remove 30 horas consecutivas (> 24 h), mas cobertura permanece > 99%
        gap_start = recs[200].ts
        gapped = recs[:200] + recs[230:]

        res_am = evaluate_station_season_qc(
            gapped, "synthetic", "ST_GAP", "tomato", 2023, "UTC", gap_policy="mask_with_warmup"
        )
        assert res_am.passed is True
        assert res_am.max_gap_hours == 30
        assert res_am.n_gap_hours == 30

        # Sensibilidade original reject_24h reprova a mesma serie
        res_24 = evaluate_station_season_qc(
            gapped, "synthetic", "ST_GAP", "tomato", 2023, "UTC", gap_policy="reject_24h"
        )
        assert res_24.passed is False
        assert "max_gap_gt_24h" in res_24.reasons

        # Verifica mascara exata para Mills (30 h de lacuna + 9 h de aquecimento = 39 h)
        masked_mills = compute_masked_hours_for_rule(
            gapped, "mills_revised", "tomato", 2023, "UTC"
        )
        assert len(masked_mills) == 30 + 9
        assert gap_start in masked_mills
        assert (gap_start + timedelta(hours=38)) in masked_mills
        assert (gap_start + timedelta(hours=39)) not in masked_mills
        assert event_touches_masked_hours(gap_start + timedelta(hours=35), gap_start + timedelta(hours=42), masked_mills)
        assert not event_touches_masked_hours(gap_start + timedelta(hours=40), gap_start + timedelta(hours=46), masked_mills)

    def test_amended_qc_still_rejects_below_95_coverage_and_sensor_drift(self):
        recs = self._clean_season(date(2023, 5, 1), date(2023, 9, 30))
        # Cobertura < 95% continua reprovando
        short = recs[300:]
        res_cov = evaluate_station_season_qc(short, "synthetic", "ST_LOW", "tomato", 2023, "UTC")
        assert res_cov.passed is False
        assert "coverage_below_0.95" in res_cov.reasons

        # Sensor travado continua reprovando
        stuck = [HourlyRecord(r.ts, r.temp_c, r.rh_pct, r.precip_mm, wet=True) for r in recs]
        res_stuck = evaluate_station_season_qc(stuck, "synthetic", "ST_DRIFT", "tomato", 2023, "UTC")
        assert res_stuck.passed is False
        assert "dry_midday_wet_above_0.15" in res_stuck.reasons


# ==========================================================================
# 2. Emenda 2: Regra 3-10 temperatura minima vs media diaria
# ==========================================================================
class TestRule310TemperatureAmendment:
    def test_diurnal_cycle_distinguishes_daily_min_from_daily_mean(self):
        # Dia com minima 8 C de madrugada e maxima 18 C a tarde -> media = 13 C (>= 10), minima = 8 C (< 10)
        recs: list[HourlyRecord] = []
        d = date(2023, 5, 10)
        for hr in range(24):
            t = 8.0 if hr < 12 else 18.0
            recs.append(
                HourlyRecord(
                    ts=datetime(d.year, d.month, d.day, hr, 0, tzinfo=UTC),
                    temp_c=t,
                    rh_pct=85.0,
                    precip_mm=15.0 if hr == 14 else 0.0,
                    wet=True,
                )
            )
        # Padrao emendado (daily_min): NAO dispara porque T_min = 8 C < 10 C
        evs_min = detect_rule_3_10(recs, tz_name="UTC")
        assert evs_min == []

        # Versao original v2-rules (daily_mean): DISPARA porque T_mean = 13 C >= 10 C
        evs_mean = detect_rule_3_10(recs, tz_name="UTC", temp_aggregation="daily_mean")
        assert len(evs_mean) == 1
        assert evs_mean[0].temp_min_c == pytest.approx(8.0)
        assert evs_mean[0].temp_mean_c == pytest.approx(13.0)
        assert evs_mean[0].temp_aggregation == "daily_mean"


# ==========================================================================
# 3. Estimadores de molhamento foliar (`vitirule_v2/lwd.py`)
# ==========================================================================
class TestLwdEstimators:
    def test_lwd_module_uses_only_stdlib(self):
        forbidden = {"numpy", "pandas", "scipy", "requests", "leaf_wetness", "downy_mildew"}
        tree = ast.parse((ROOT / "vitirule_v2" / "lwd.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in forbidden

    def test_primary_rh90_rain_never_reads_sensor_flag(self):
        assert PRIMARY_LWD_METHOD == "rh90_rain"
        t0 = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
        # Coloca wet=True (sensor) numa hora seca e wet=False numa hora chuvosa:
        # o estimador deve ignorar `rec.wet` completamente (zero inverse crime).
        recs = [
            HourlyRecord(t0, temp_c=25.0, rh_pct=50.0, precip_mm=0.0, wet=True),
            HourlyRecord(t0 + timedelta(hours=1), temp_c=20.0, rh_pct=90.0, precip_mm=0.0, wet=False),
            HourlyRecord(t0 + timedelta(hours=2), temp_c=20.0, rh_pct=60.0, precip_mm=0.2, wet=False),
        ]
        out = apply_lwd_estimator(recs, method="rh90_rain")
        assert [r.wet for r in out] == [False, True, True]

    def test_dpd_hysteresis_gillespie1993_thresholds(self):
        # Inicio em DPD <= 1.8 C; permanece molhado em DPD = 2.8 C (histerese); seca em DPD >= 3.8 C
        t0 = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
        # A 20 C: RH 92% -> DPD ~ 1.3 C (inicia); RH 84% -> DPD ~ 2.8 C (mantem); RH 78% -> DPD ~ 4.0 C (seca)
        assert 20.0 - magnus_dewpoint_c(20.0, 92.0) <= 1.8
        assert 1.8 < 20.0 - magnus_dewpoint_c(20.0, 84.0) < 3.8
        assert 20.0 - magnus_dewpoint_c(20.0, 78.0) >= 3.8
        recs = [
            HourlyRecord(t0, temp_c=20.0, rh_pct=84.0, precip_mm=0.0),                        # seco inicialmente
            HourlyRecord(t0 + timedelta(hours=1), temp_c=20.0, rh_pct=92.0, precip_mm=0.0),   # inicia
            HourlyRecord(t0 + timedelta(hours=2), temp_c=20.0, rh_pct=84.0, precip_mm=0.0),   # mantem (histerese)
            HourlyRecord(t0 + timedelta(hours=3), temp_c=20.0, rh_pct=78.0, precip_mm=0.0),   # seca
        ]
        assert estimate_lwd_flags(recs, method="dpd_hysteresis") == [False, True, True, False]

    def test_cart_kim2002_and_fao56_wind_scaling(self):
        assert wind_10m_to_2m_ms(10.0) == pytest.approx(7.48, abs=0.02)
        t0 = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
        recs = [
            HourlyRecord(t0, temp_c=22.0, rh_pct=55.0, precip_mm=0.0, wind_ms=2.0),           # DPD > 3.7 -> seco
            HourlyRecord(t0 + timedelta(hours=1), temp_c=18.0, rh_pct=96.0, precip_mm=0.0, wind_ms=0.8),  # calmo umido -> molhado
            HourlyRecord(t0 + timedelta(hours=2), temp_c=20.0, rh_pct=70.0, precip_mm=0.5, wind_ms=4.0),  # chuva -> molhado
        ]
        assert estimate_lwd_flags(recs, method="cart_kim2002", wind_height_m=2.0) == [False, True, True]


# ==========================================================================
# 4. Fontes: NASA POWER UTC explicito, Open-Meteo e metadados de grade
# ==========================================================================
class TestWeatherSourcesAndGridMetadata:
    def test_nasa_power_params_force_explicit_utc_time_standard(self):
        params = build_nasa_power_params(44.7526, -0.56077, "2023-05-01", "2023-05-02")
        assert params["time-standard"] == "UTC"
        assert params["start"] == "20230501"
        assert params["end"] == "20230502"

    def test_nasa_power_parser_rejects_lst_and_converts_units_in_utc(self):
        lst_payload = {
            "header": {"time_standard": "LST", "fill_value": -999.0},
            "geometry": {"coordinates": [-0.561, 44.753, 38.4]},
            "properties": {"parameter": {"T2M": {"2023061512": 22.0}}},
        }
        with pytest.raises(ValueError, match="UTC"):
            parse_nasa_power_payload(lst_payload, 44.7526, -0.56077)

        utc_payload = {
            "header": {"time_standard": "UTC", "fill_value": -999.0},
            "geometry": {"coordinates": [-0.561, 44.753, 38.4]},
            "properties": {
                "parameter": {
                    "T2M": {"2023061512": 22.5, "2023061513": -999.0},
                    "RH2M": {"2023061512": 65.0, "2023061513": -999.0},
                    "PRECTOTCORR": {"2023061512": 0.4, "2023061513": 0.0},
                    "WS2M": {"2023061512": 2.1, "2023061513": 1.8},
                    "ALLSKY_SFC_SW_DWN": {"2023061512": 1.8, "2023061513": -999.0},
                }
            },
        }
        recs, meta = parse_nasa_power_payload(utc_payload, 44.7526, -0.56077)
        assert len(recs) == 2
        assert recs[0].ts == datetime(2023, 6, 15, 12, 0, tzinfo=UTC)
        assert recs[0].temp_c == 22.5
        assert recs[0].rad_wm2 == pytest.approx(1.8 * MJ_PER_HR_TO_WM2, abs=0.01)
        assert recs[1].temp_c is None  # sentinela -999 virou None
        assert meta["time_standard"] == "UTC"
        assert meta["wind_height_m"] == 2.0
        assert meta["grid_elev_m"] == 38.4

    def test_nasa_power_fetch_uses_utc_param_and_disk_cache(self, tmp_path):
        captured: dict = {}

        class _DummyResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "header": {"time_standard": "UTC", "fill_value": -999.0},
                    "geometry": {"coordinates": [-0.561, 44.753, 38.4]},
                    "properties": {
                        "parameter": {
                            "T2M": {"2023061500": 15.0},
                            "RH2M": {"2023061500": 90.0},
                            "PRECTOTCORR": {"2023061500": 0.0},
                            "WS2M": {"2023061500": 1.0},
                            "ALLSKY_SFC_SW_DWN": {"2023061500": 0.0},
                        }
                    },
                }

        class _DummySession:
            headers: dict = {}
            calls = 0
            def get(self, url, params=None, timeout=None):
                self.calls += 1
                captured["params"] = dict(params or {})
                return _DummyResp()

        sess = _DummySession()
        recs1, _ = fetch_nasa_power_hourly(
            44.7526, -0.56077, "2023-06-15", "2023-06-15",
            cache_dir=tmp_path, station_tag="test", session=sess
        )
        recs2, _ = fetch_nasa_power_hourly(
            44.7526, -0.56077, "2023-06-15", "2023-06-15",
            cache_dir=tmp_path, station_tag="test", session=sess
        )
        assert captured["params"]["time-standard"] == "UTC"
        assert sess.calls == 1  # segunda leitura veio do cache em disco
        assert recs1 == recs2

    def test_open_meteo_parser_and_grid_distance_elevation(self):
        payload = {
            "latitude": 44.8,
            "longitude": -0.6,
            "elevation": 25.0,
            "timezone": "GMT",
            "hourly": {
                "time": [1686830400],
                "temperature_2m": [21.3],
                "relative_humidity_2m": [72.0],
                "precipitation": [0.0],
                "wind_speed_10m": [3.2],
                "shortwave_radiation": [550.0],
            },
        }
        recs, meta = parse_open_meteo_hourly_payload(payload)
        assert len(recs) == 1
        assert recs[0].ts == datetime(2023, 6, 15, 12, 0, tzinfo=UTC)
        assert meta["grid_elev_m"] == 25.0

        gm = build_station_grid_match(
            "inrae", "33080002", "Bordeaux", "era5_land",
            44.75260, -0.56077, 20.0,
            meta["grid_lat"], meta["grid_lon"], meta["grid_elev_m"],
        )
        assert 5.0 < gm.distance_km < 7.0
        assert gm.elev_diff_m == pytest.approx(5.0)
        assert nearest_merra2_center(44.7526, -0.56077) == (45.0, -0.625)
        assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.195, abs=0.1)

    def test_era5_land_fetch_uses_era5_seamless_and_rejects_all_null_precip(self, tmp_path):
        from vitirule_v2.sources.open_meteo import fetch_era5_land

        captured: dict = {}

        class _NullPrecipResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "latitude": 44.8, "longitude": -0.6, "elevation": 25.0, "timezone": "GMT",
                    "hourly": {
                        "time": [1686830400],
                        "temperature_2m": [20.0],
                        "relative_humidity_2m": [80.0],
                        "precipitation": [None],
                        "wind_speed_10m": [None],
                        "shortwave_radiation": [None],
                    },
                }

        class _DummySession:
            headers: dict = {}
            def get(self, url, params=None, timeout=None):
                captured["params"] = dict(params or {})
                return _NullPrecipResp()

        with pytest.raises(ValueError, match="precipitation"):
            fetch_era5_land(44.7526, -0.56077, "2023-06-15", "2023-06-15", cache_dir=tmp_path, station_tag="t", session=_DummySession())
        assert captured["params"]["models"] == "era5_seamless"
