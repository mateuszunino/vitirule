#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lwd_sensor_validation.py
========================
Validação empírica de `leaf_wetness.py` contra sensores reais de molhamento
foliar em duas redes independentes da Europa:

1. **INRAE AgroClim** (DOI: 10.57745/BQ0BWB; Furusho-Percot et al., *Data in
   Brief* 2025, PMC12266558): 4 estações em regiões vitícolas francesas
   (Bordeaux-Couhins, Alsace-Colmar, Champagne-Fagnières, Bourgogne-Bretenière),
   temporadas de abril a setembro de 2022–2024 (~52.600 horas reais).
2. **Politecnico di Torino / iXem Labs** (Mendeley Data, DOI:
   10.17632/sd4b8vpvyb.1): 7 estações na Itália com sensor capacitivo de
   molhamento de dupla face (abril a setembro, ~27.700 horas reais).

Executa **duas comparações pareadas** sobre as mesmas horas e sensores:
* **A (`station_weather`)**      : estimadores alimentados com o clima medido
  NA PRÓPRIA estação -> isola o erro intrínseco de cada modelo de LWD.
* **B (`open_meteo_reanalysis`)**: estimadores alimentados com a reanálise
  Open-Meteo Archive nas mesmas coordenadas `(lat, lon)` -> mede o erro total
  operacional e decompõe a penalidade vinda da reanálise (`B - A`).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import downy_mildew as dm
import leaf_wetness as lw

log = logging.getLogger("lwd_sensor_validation")

UTC = timezone.utc

INRAE_STATIONS = [
    {
        "id": "33080002",
        "name": "Bordeaux (Couhins, INRAE)",
        "file": "data/lwd_sensors/inrae/33080002_bordeaux_couhins.tab",
        "lat": 44.75260,
        "lon": -0.56077,
        "tz": "Europe/Paris",
    },
    {
        "id": "68066002",
        "name": "Alsace (Colmar-Huben, INRAE)",
        "file": "data/lwd_sensors/inrae/68066002_alsace_colmar.tab",
        "lat": 48.06429,
        "lon": 7.33012,
        "tz": "Europe/Paris",
    },
    {
        "id": "51242002",
        "name": "Champagne (Fagnières, INRAE)",
        "file": "data/lwd_sensors/inrae/51242002_champagne_fagnieres.tab",
        "lat": 48.94978,
        "lon": 4.31402,
        "tz": "Europe/Paris",
    },
    {
        "id": "21106002",
        "name": "Bourgogne (Bretenière, INRAE)",
        "file": "data/lwd_sensors/inrae/21106002_bourgogne_breteniere.tab",
        "lat": 47.23917,
        "lon": 5.10232,
        "tz": "Europe/Paris",
    },
]


def load_inrae_station(path: str | Path, year_start: int = 2022, year_end: int = 2024) -> pd.DataFrame:
    """
    Lê `.tab` horário da rede INRAE AgroClim (hora 1..24 UTC, `h` em horas e
    décimos [0..1], `vt` em km/h -> m/s a 2 m, `rg` em J/cm² -> W/m²).
    """
    df = pd.read_csv(path, sep="\t", low_memory=False)
    df["year"] = df["date_j"].str.slice(0, 4).astype(int)
    df["month"] = df["date_j"].str.slice(5, 7).astype(int)
    sub = df[(df["year"].between(year_start, year_end)) & (df["month"].between(4, 9))].copy()

    # Converte date_j + heure (1..24 UTC) para timestamp UTC no fim da hora
    base_dt = pd.to_datetime(sub["date_j"], utc=True)
    hrs = pd.to_numeric(sub["heure"], errors="coerce").fillna(0).astype(int)
    sub["ts"] = base_dt + pd.to_timedelta(hrs, unit="h")

    out = pd.DataFrame({
        "ts": sub["ts"],
        "temp_c": pd.to_numeric(sub["t"], errors="coerce"),
        "rh_pct": pd.to_numeric(sub["u"], errors="coerce"),
        "precip_mm": pd.to_numeric(sub["rr"], errors="coerce").fillna(0.0),
        "wind_ms": pd.to_numeric(sub["vt"], errors="coerce") / 3.6,            # km/h -> m/s (altura ~2 m)
        "rad_wm2": pd.to_numeric(sub["rg"], errors="coerce") * (10_000.0 / 3600.0),  # J/cm²/h -> W/m²
        "sensor_hours": pd.to_numeric(sub["h"], errors="coerce"),
    })
    out = out.dropna(subset=["temp_c", "rh_pct", "sensor_hours"]).copy()
    out["leaf_wet_sensor"] = (out["sensor_hours"] >= 0.5).astype(int)
    out = out.set_index("ts").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def load_polito_site(path: str | Path, wet_threshold: float = 20.0) -> pd.DataFrame:
    """Lê CSV horário do Politecnico di Torino (UTC, sensor capacitivo 0..100)."""
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["time"], utc=True)
    sub = df[df["ts"].dt.month.between(4, 9)].copy()
    lt = pd.to_numeric(sub["leaf_top"], errors="coerce")
    out = pd.DataFrame({
        "ts": sub["ts"],
        "temp_c": pd.to_numeric(sub["temperature"], errors="coerce"),
        "rh_pct": pd.to_numeric(sub["rh"], errors="coerce"),
        "precip_mm": pd.to_numeric(sub["rain"], errors="coerce").fillna(0.0),
        "wind_ms": pd.to_numeric(sub["wind_speed"], errors="coerce"),
        "rad_wm2": np.nan,
        "sensor_raw": lt,
    })
    out = out.dropna(subset=["temp_c", "rh_pct", "sensor_raw"]).copy()
    out["leaf_wet_sensor"] = (out["sensor_raw"] >= wet_threshold).astype(int)
    out = out.set_index("ts").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _eval_estimators(
    weather_df: pd.DataFrame,
    sensor_series: pd.Series,
    wind_height_m: float,
    local_tz_name: str,
) -> dict[str, dict]:
    """Avalia os 4 estimadores de `leaf_wetness.py` alinhados sobre as mesmas horas do sensor."""
    common_idx = weather_df.index.intersection(sensor_series.index)
    w_aligned = weather_df.loc[common_idx]
    y_true = (sensor_series.loc[common_idx].to_numpy(dtype=float) > 0.5).astype(int)
    tz = lw.ea.ZoneInfo(local_tz_name)
    day_label = (common_idx.tz_convert(tz) - pd.Timedelta(hours=12)).normalize()
    daily_true = pd.Series(y_true, index=common_idx).groupby(day_label).sum()

    res: dict[str, dict] = {}
    for method in lw.VALID_METHODS:
        pred = (
            lw.estimate_leaf_wetness(w_aligned, method=method, wind_height_m=wind_height_m).to_numpy(dtype=float) > 0.5
        ).astype(int)
        tp = int(np.sum((pred == 1) & (y_true == 1)))
        fp = int(np.sum((pred == 1) & (y_true == 0)))
        fn = int(np.sum((pred == 0) & (y_true == 1)))
        tn = int(np.sum((pred == 0) & (y_true == 0)))
        acc = (tp + tn) / max(tp + fp + fn + tn, 1)
        pod = tp / max(tp + fn, 1)
        far = fp / max(tp + fp, 1)
        f1 = (2 * tp) / max(2 * tp + fp + fn, 1)
        csi = tp / max(tp + fp + fn, 1)
        daily_pred = pd.Series(pred, index=common_idx).groupby(day_label).sum()
        mae_h = float(np.mean(np.abs(daily_pred - daily_true)))
        bias_h = float(np.mean(daily_pred - daily_true))
        res[method] = {
            "n_hours": int(len(y_true)),
            "obs_wet_pct": round(100.0 * float(y_true.mean()), 2),
            "pred_wet_pct": round(100.0 * float(pred.mean()), 2),
            "accuracy": round(acc, 4),
            "pod": round(pod, 4),
            "far": round(far, 4),
            "f1": round(f1, 4),
            "csi": round(csi, 4),
            "daily_lwd_mae_h": round(mae_h, 3),
            "daily_lwd_bias_h": round(bias_h, 3),
        }
    return res


def _fetch_open_meteo_for_range(lat: float, lon: float, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    rows = dm.fetch_rich_historical_weather(
        start_ts.date().isoformat(), end_ts.date().isoformat(), lat, lon
    )
    return lw.normalize_rich_weather(rows)


def _aggregate_network(station_reports: list[dict], key: str) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for method in lw.VALID_METHODS:
        items = [s[key][method] for s in station_reports]
        weights = np.array([it["n_hours"] for it in items], dtype=float)
        wavg = lambda field: round(float(np.average([it[field] for it in items], weights=weights)), 4)
        agg[method] = {
            "total_hours": int(weights.sum()),
            "obs_wet_pct": round(wavg("obs_wet_pct"), 2),
            "pred_wet_pct": round(wavg("pred_wet_pct"), 2),
            "accuracy": wavg("accuracy"),
            "pod": wavg("pod"),
            "far": wavg("far"),
            "f1": wavg("f1"),
            "csi": wavg("csi"),
            "daily_lwd_mae_h": round(wavg("daily_lwd_mae_h"), 3),
            "daily_lwd_bias_h": round(wavg("daily_lwd_bias_h"), 3),
        }
    return agg


def run_validation() -> dict:
    # 1. INRAE AgroClim (4 estações vitícolas francesas, 2022–2024 abril–setembro)
    inrae_reports: list[dict] = []
    for st in INRAE_STATIONS:
        log.info("Validando INRAE %s ...", st["name"])
        st_df = load_inrae_station(st["file"], 2022, 2024)
        om_df = _fetch_open_meteo_for_range(st["lat"], st["lon"], st_df.index.min(), st_df.index.max())
        res_station = _eval_estimators(st_df, st_df["leaf_wet_sensor"], wind_height_m=2.0, local_tz_name=st["tz"])
        res_om = _eval_estimators(om_df, st_df["leaf_wet_sensor"], wind_height_m=10.0, local_tz_name=st["tz"])
        inrae_reports.append({
            "station_id": st["id"],
            "name": st["name"],
            "lat": st["lat"],
            "lon": st["lon"],
            "station_weather": res_station,
            "open_meteo_reanalysis": res_om,
        })

    # 2. Politecnico di Torino (7 estações italianas, abril–setembro)
    polito_sites = json.loads(Path("data/lwd_sensors/polito/sites.json").read_text(encoding="utf-8"))["sites"]
    polito_reports: list[dict] = []
    for site in sorted(polito_sites, key=lambda x: x["ref"]):
        log.info("Validando Polito %s ...", site["ref"])
        st_df = load_polito_site(Path("data/lwd_sensors/polito") / site["ref"], wet_threshold=20.0)
        om_df = _fetch_open_meteo_for_range(site["lat"], site["lon"], st_df.index.min(), st_df.index.max())
        res_station = _eval_estimators(st_df, st_df["leaf_wet_sensor"], wind_height_m=2.0, local_tz_name="Europe/Rome")
        res_om = _eval_estimators(om_df, st_df["leaf_wet_sensor"], wind_height_m=10.0, local_tz_name="Europe/Rome")
        polito_reports.append({
            "station_id": site["ref"],
            "lat": site["lat"],
            "lon": site["lon"],
            "elevation_m": site["elevation"],
            "station_weather": res_station,
            "open_meteo_reanalysis": res_om,
        })

    # Também calcula Polito sem site2 (que apresentou 99,9 % > 0 — provável deriva de sensor)
    polito_clean = [r for r in polito_reports if r["station_id"] != "site2.csv"]

    out = {
        "inrae_agroclim": {
            "doi": "10.57745/BQ0BWB",
            "period": "2022-2024 (Apr-Sep)",
            "pooled_station_weather": _aggregate_network(inrae_reports, "station_weather"),
            "pooled_open_meteo_reanalysis": _aggregate_network(inrae_reports, "open_meteo_reanalysis"),
            "stations": inrae_reports,
        },
        "politecnico_torino": {
            "doi": "10.17632/sd4b8vpvyb.1",
            "wet_threshold_raw": 20.0,
            "pooled_all7_station_weather": _aggregate_network(polito_reports, "station_weather"),
            "pooled_all7_open_meteo_reanalysis": _aggregate_network(polito_reports, "open_meteo_reanalysis"),
            "pooled_6clean_station_weather": _aggregate_network(polito_clean, "station_weather"),
            "pooled_6clean_open_meteo_reanalysis": _aggregate_network(polito_clean, "open_meteo_reanalysis"),
            "stations": polito_reports,
        },
    }
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    report = run_validation()
    out_path = Path("data/fase2/lwd_sensor_validation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Imprime resumo compacto das duas redes
    for net_name, blk in (
        ("INRAE AgroClim (4 estacoes viticolas FR, 52.6k h)", report["inrae_agroclim"]),
        ("Politecnico di Torino (6 estacoes limpas IT, 23.7k h)", {
            "pooled_station_weather": report["politecnico_torino"]["pooled_6clean_station_weather"],
            "pooled_open_meteo_reanalysis": report["politecnico_torino"]["pooled_6clean_open_meteo_reanalysis"],
        }),
        ("Politecnico di Torino (todas 7 estacoes IT, 27.7k h)", {
            "pooled_station_weather": report["politecnico_torino"]["pooled_all7_station_weather"],
            "pooled_open_meteo_reanalysis": report["politecnico_torino"]["pooled_all7_open_meteo_reanalysis"],
        }),
    ):
        print(f"\n=== {net_name} ===")
        print("Method           | Station: Acc / F1 / CSI / MAE(h) / Bias(h) | OpenMeteo: Acc / F1 / CSI / MAE(h) / Bias(h)")
        for m in lw.VALID_METHODS:
            a = blk["pooled_station_weather"][m]
            b = blk["pooled_open_meteo_reanalysis"][m]
            print(
                f"{m:16s} | {a['accuracy']:.3f} / {a['f1']:.3f} / {a['csi']:.3f} / {a['daily_lwd_mae_h']:5.2f} / {a['daily_lwd_bias_h']:+6.2f}"
                f" | {b['accuracy']:.3f} / {b['f1']:.3f} / {b['csi']:.3f} / {b['daily_lwd_mae_h']:5.2f} / {b['daily_lwd_bias_h']:+6.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
