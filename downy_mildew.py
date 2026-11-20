#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
downy_mildew.py
===============
Modelo agrometeorológico e índices de risco para o míldio da videira
(*Plasmopara viticola*), desenhado para integrar o motor multi-patossistema
de assimilação epidemiológica (foco em regiões vitícolas da Europa — Moselle/LU,
Bordeaux/FR — e Santa Catarina — São Joaquim/SC).

Referências agronômicas implementadas:
* Temperaturas cardinais de *P. viticola*: Tmin = 8 °C, Tot = 22 °C, Tmax = 30 °C
  (Magarey et al. 1991; Rossi et al. 2008; Orlandini et al. 2008).
* Regra 3-10 (Baldacci 1947/1950): infecção primária por oósporos quando
  T_média >= 10 °C, chuva >= 10 mm em 24–48 h e broto >= 10 cm.
* Curva de incubação de Goidànich / Müller-Sleumer: progresso diário (%) da
  incubação em função da temperatura (4 dias a ~23 °C; ~12–15 dias a 12 °C).
* Risco secundário diário (escala 0–4, baseado em Blaeser & Weltzien 1979 /
  Magarey et al. 1991 / Caffi et al. 2010): requer molhamento estimado por
  modelo físico/empírico (`cart_kim2002` ou `dpd_hysteresis`), nunca apenas
  UR >= 85 %.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import epidemiology_assimilation as ea
import leaf_wetness as lw
import weather_collector as wc

UTC = timezone.utc

# Parâmetros de *Plasmopara viticola* compatíveis com `epidemiology_assimilation.PATHOGENS`
PLASMOPARA_PARAMS: dict[str, float] = {
    "tmin": 8.0,
    "topt": 22.0,
    "tmax": 30.0,
    "dry_factor": 0.08,
    "r_prior": 0.30,
    "r_prior_gompertz": 0.16,
    "r_prior_sd_log": 0.70,
    "y0_prior_pct": 0.20,
}

# Regiões vitícolas de referência para retrospectiva e benchmarks históricos
VINEYARD_REGIONS: dict[str, dict[str, Any]] = {
    "moselle_lu": {
        "name": "Moselle (Remich, Luxemburgo)",
        "latitude": 49.5447,
        "longitude": 6.3669,
        "tz": "Europe/Luxembourg",
        "growing_season_months": (4, 5, 6, 7, 8, 9),   # Abril a Setembro (Hemisfério Norte)
    },
    "bordeaux_fr": {
        "name": "Bordeaux (Saint-Émilion, França)",
        "latitude": 44.8944,
        "longitude": -0.1558,
        "tz": "Europe/Paris",
        "growing_season_months": (4, 5, 6, 7, 8, 9),
    },
    "alsace_fr": {
        "name": "Alsace (Colmar, França)",
        "latitude": 48.0794,
        "longitude": 7.3585,
        "tz": "Europe/Paris",
        "growing_season_months": (4, 5, 6, 7, 8, 9),
    },
    "sao_joaquim_sc": {
        "name": "São Joaquim (Planalto Serrano, SC)",
        "latitude": -28.2936,
        "longitude": -49.9317,
        "tz": "America/Sao_Paulo",
        "growing_season_months": (10, 11, 12, 1, 2, 3),  # Outubro a Março (Hemisfério Sul)
    },
}


def register_downy_mildew_pathogen() -> None:
    """Registra `mildio_videira` em `epidemiology_assimilation.PATHOGENS` sem alterar o módulo base."""
    if "mildio_videira" not in ea.PATHOGENS:
        ea.PATHOGENS["mildio_videira"] = dict(PLASMOPARA_PARAMS)


def fetch_rich_historical_weather(
    start_date: str | date,
    end_date: str | date,
    latitude: float,
    longitude: float,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Baixa série horária histórica completa do Open-Meteo Archive incluindo
    T, UR, ponto de orvalho, chuva, vento a 10 m e radiação solar (necessários
    para CART de Kim et al. 2002 e DPD com histerese).
    """
    s_str = start_date.isoformat() if isinstance(start_date, date) else str(start_date)
    e_str = end_date.isoformat() if isinstance(end_date, date) else str(end_date)
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "vineyard-dss-agromet/1.0 (research)")
    resp = sess.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": s_str,
            "end_date": e_str,
            "hourly": (
                "temperature_2m,relative_humidity_2m,dew_point_2m,"
                "precipitation,wind_speed_10m,shortwave_radiation"
            ),
            "timezone": "GMT",
            "timeformat": "unixtime",
            "wind_speed_unit": "ms",
        },
        timeout=(5.0, 45.0),
    )
    resp.raise_for_status()
    payload = resp.json()
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    get_col = lambda k: hourly.get(k) or [None] * len(times)
    t_col = get_col("temperature_2m")
    rh_col = get_col("relative_humidity_2m")
    td_col = get_col("dew_point_2m")
    p_col = get_col("precipitation")
    w_col = get_col("wind_speed_10m")
    r_col = get_col("shortwave_radiation")

    out: list[dict] = []
    for i, epoch in enumerate(times):
        ts = datetime.fromtimestamp(int(epoch), tz=UTC)
        out.append({
            "ts": ts.isoformat(),
            "temp_c": wc.to_float(t_col[i]),
            "rh_pct": wc.to_float(rh_col[i]),
            "dewpoint_c": wc.to_float(td_col[i]),
            "precip_mm": wc.to_float(p_col[i]),
            "wind_ms": wc.to_float(w_col[i]),
            "rad_wm2": wc.to_float(r_col[i]),
        })
    return out


# --------------------------------------------------------------------------
# Modelos clássicos de *Plasmopara viticola*
# --------------------------------------------------------------------------
# Tabela de Müller-Sleumer / Goidànich (1964): progresso diário (%) de incubação
# de *Plasmopara viticola* (ex.: 4 d a 22–25 °C = 25 %/d; ~13 d a 12 °C = 7,7 %/d)
_GOIDANICH_T = np.array([8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 25.0, 28.0, 30.0])
_GOIDANICH_PCT = np.array([0.0, 5.0, 7.7, 10.0, 13.3, 16.7, 20.0, 25.0, 25.0, 16.7, 0.0])


def goidanich_daily_incubation_pct(temp_mean_c: float, rh_mean_pct: float = 80.0) -> float:
    """
    Progresso diário (%) da incubação de *Plasmopara viticola* segundo a tabela
    de Müller-Sleumer / Goidànich (1964):
      - 12 °C -> 7,7 %/dia (~13 dias)
      - 16 °C -> 13,3 %/dia (~7,5 dias)
      - 20 °C -> 20,0 %/dia (~5 dias)
      - 22–25 °C -> 25,0 %/dia (~4 dias)
      - <= 8 °C ou >= 30 °C -> 0 %/dia
    Ajuste leve para umidade baixa (UR < 75 %) conforme Goidànich (1964).
    """
    if not np.isfinite(temp_mean_c) or temp_mean_c <= 8.0 or temp_mean_c >= 30.0:
        return 0.0
    base_pct = float(np.interp(temp_mean_c, _GOIDANICH_T, _GOIDANICH_PCT))
    rh_factor = 1.0 if (not np.isfinite(rh_mean_pct) or rh_mean_pct >= 75.0) else 0.85
    return round(base_pct * rh_factor, 3)


def compute_downy_mildew_daily(
    weather: Any,
    lwd_method: str = "cart_kim2002",
    local_tz_name: str = "Europe/Luxembourg",
    shoots_ge_10cm: bool = True,
) -> pd.DataFrame:
    """
    Calcula diariamente (janela 12h–12h local) os índices de *Plasmopara viticola*:
    * `lwd_hours`      : horas molhadas segundo `lwd_method` (ex.: `cart_kim2002`)
    * `night_wet_hours`: horas molhadas no período noturno (20h–07h locais)
    * `rain_24h_mm`    : precipitação acumulada em 24 h
    * `rain_48h_mm`    : precipitação acumulada em 48 h
    * `rule_3_10`      : gatilho de infecção primária (Baldacci: T >= 10 °C,
                         chuva 48 h >= 10 mm, broto >= 10 cm)
    * `incubation_pct` : progresso diário de incubação (Goidànich)
    * `secondary_sv`   : severidade diária de infecção secundária (0 a 4)
                         baseada em temperatura + molhamento + esporulação noturna
    """
    df = lw.normalize_rich_weather(weather)
    if df.empty:
        return pd.DataFrame()

    wet = lw.estimate_leaf_wetness(df, method=lwd_method)
    tz = ZoneInfo(local_tz_name)
    local_idx = df.index.tz_convert(tz)
    df = df.assign(
        wet=wet,
        local_hour=local_idx.hour,
        day=(local_idx - pd.Timedelta(hours=12)).normalize().date,
    )

    records: list[dict] = []
    prev_rain = 0.0
    for day_val, grp in df.groupby("day"):
        t_mean = float(grp["temp_c"].mean()) if grp["temp_c"].notna().any() else np.nan
        rh_mean = float(grp["rh_pct"].mean()) if grp["rh_pct"].notna().any() else np.nan
        rain_24 = float(grp["precip_mm"].fillna(0.0).sum())
        rain_48 = rain_24 + prev_rain
        prev_rain = rain_24

        wet_grp = grp[grp["wet"] > 0]
        lwd_h = int(len(wet_grp))
        wet_temp = float(wet_grp["temp_c"].mean()) if lwd_h > 0 else np.nan
        night_wet = grp[(grp["wet"] > 0) & ((grp["local_hour"] >= 20) | (grp["local_hour"] <= 7))]
        night_wet_h = int(len(night_wet))
        night_temp = float(night_wet["temp_c"].mean()) if night_wet_h > 0 else np.nan

        # Regra 3-10 (Baldacci): infecção primária
        rule_3_10 = bool(shoots_ge_10cm and np.isfinite(t_mean) and t_mean >= 10.0 and rain_48 >= 10.0)

        # Esporulação noturna (Blaeser/Rossi: >= 4 h úmidas à noite com T >= 13 °C)
        sporulation_ok = bool(night_wet_h >= 4 and np.isfinite(night_temp) and 13.0 <= night_temp <= 28.0)

        # Severidade diária de infecção secundária (0..4) por T_molhada e horas molhadas
        sv = 0
        if lwd_h >= 2 and np.isfinite(wet_temp) and 10.0 <= wet_temp <= 29.0:
            if 18.0 <= wet_temp <= 25.0:
                if lwd_h >= 10 and (sporulation_ok or rain_24 >= 2.0):
                    sv = 4
                elif lwd_h >= 6 and (sporulation_ok or rain_24 >= 1.0):
                    sv = 3
                elif lwd_h >= 4:
                    sv = 2
                elif lwd_h >= 2:
                    sv = 1
            elif 13.0 <= wet_temp < 18.0 or 25.0 < wet_temp <= 28.0:
                if lwd_h >= 12 and (sporulation_ok or rain_24 >= 2.0):
                    sv = 3
                elif lwd_h >= 7:
                    sv = 2
                elif lwd_h >= 4:
                    sv = 1
            else:
                if lwd_h >= 8:
                    sv = 1

        records.append({
            "day": day_val,
            "temp_mean_c": round(t_mean, 2) if np.isfinite(t_mean) else None,
            "rh_mean_pct": round(rh_mean, 1) if np.isfinite(rh_mean) else None,
            "rain_24h_mm": round(rain_24, 2),
            "rain_48h_mm": round(rain_48, 2),
            "lwd_hours": lwd_h,
            "night_wet_hours": night_wet_h,
            "rule_3_10": rule_3_10,
            "sporulation_ok": sporulation_ok,
            "incubation_pct": goidanich_daily_incubation_pct(t_mean, rh_mean),
            "secondary_sv": sv,
        })
    return pd.DataFrame(records)
