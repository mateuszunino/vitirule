#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leaf_wetness.py
===============
Modelos agrometeorológicos publicados para estimativa horária de molhamento
foliar (Leaf Wetness Duration — LWD), comparados ao critério simples UR >= 85 %.

Referências implementadas:
1. `rh85`             : linha de base do projeto (UR >= 85 % ou chuva > 0).
2. `rh90_hysteresis`  : limiar de UR com histerese (início >= 90 %, seca < 80 %
                        ou radiação solar > 250 W/m²; Sentelhas et al. 2008).
3. `dpd_hysteresis`   : depressão do ponto de orvalho DPD = T - Td com histerese
                        (início <= 1,8 °C, seca >= 3,8 °C; Gillespie et al. 1993;
                        Gleason et al. 1994; Sentelhas et al. 2008).
4. `cart_kim2002`     : árvore CART/SLD de Kim et al. (2002, Plant Disease
                        86:179–185) usando T, UR, DPD e velocidade do vento
                        ajustada para altura do dossel (FAO-56 Eq. 47).

Todos os modelos consideram hora molhada quando há precipitação >= 0,1 mm/h.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

import epidemiology_assimilation as ea

RAIN_WET_MM: float = 0.1
VALID_METHODS = ("rh85", "rh90_hysteresis", "dpd_hysteresis", "cart_kim2002")


def magnus_dewpoint_c(temp_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """Ponto de orvalho pela aproximação de Magnus-Tetens (Alduchov & Eskridge 1996)."""
    t = np.asarray(temp_c, dtype=float)
    rh = np.clip(np.asarray(rh_pct, dtype=float), 1.0, 100.0)
    a, b = 17.625, 243.04
    gamma = np.log(rh / 100.0) + (a * t) / (b + t)
    return (b * gamma) / (a - gamma)


def wind_10m_to_2m(wind_10m_ms: np.ndarray) -> np.ndarray:
    """Ajuste logarítmico padrão FAO-56 (Eq. 47) de 10 m para 2 m (fator ~0,748)."""
    factor = 4.87 / math.log(67.8 * 10.0 - 5.42)
    return np.maximum(np.asarray(wind_10m_ms, dtype=float), 0.0) * factor


def normalize_rich_weather(records: Any) -> pd.DataFrame:
    """
    Normaliza série horária preservando variáveis extras usadas pelos modelos
    de molhamento (`dewpoint_c`, `wind_ms`, `rad_wm2`), indexada em UTC.
    """
    cols = ["temp_c", "rh_pct", "precip_mm", "dewpoint_c", "wind_ms", "rad_wm2"]
    if records is None:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    df = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(list(records))
    if df.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    if "ts" in df.columns:
        df.index = pd.DatetimeIndex([ea._to_utc(v) for v in df["ts"]])
    elif df.index.tz is None:
        raise ValueError("clima sem coluna 'ts' e índice sem fuso horário")
    else:
        df.index = df.index.tz_convert("UTC")
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else np.nan
    df = df[cols].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    # Calcula dewpoint_c via Magnus onde estiver ausente mas T e UR existirem
    need_td = df["dewpoint_c"].isna() & df["temp_c"].notna() & df["rh_pct"].notna()
    if need_td.any():
        df.loc[need_td, "dewpoint_c"] = magnus_dewpoint_c(
            df.loc[need_td, "temp_c"].to_numpy(),
            df.loc[need_td, "rh_pct"].to_numpy(),
        )
    return df


def estimate_leaf_wetness(
    weather: Any,
    method: str = "cart_kim2002",
    wind_height_m: float = 10.0,
) -> pd.Series:
    """
    Estima molhamento foliar horário (0.0 ou 1.0) segundo o método escolhido.

    Parâmetros
    ----------
    weather : DataFrame ou sequência de dicts horários
        Campos: `ts`, `temp_c`, `rh_pct`, `precip_mm` e opcionalmente
        `dewpoint_c`, `wind_ms`, `rad_wm2`.
    method : str
        Um dentre `rh85`, `rh90_hysteresis`, `dpd_hysteresis`, `cart_kim2002`.
    wind_height_m : float
        Altura da medição do vento (Open-Meteo fornece a 10 m; ajusta para 2 m).
    """
    if method not in VALID_METHODS:
        raise ValueError(f"método desconhecido: {method!r}. Use {VALID_METHODS}.")
    df = normalize_rich_weather(weather)
    if df.empty:
        return pd.Series(dtype=float, index=df.index)

    t = df["temp_c"].to_numpy(dtype=float)
    rh = df["rh_pct"].to_numpy(dtype=float)
    rain = np.nan_to_num(df["precip_mm"].to_numpy(dtype=float), nan=0.0)
    td = df["dewpoint_c"].to_numpy(dtype=float)
    dpd = t - td
    rad = df["rad_wm2"].to_numpy(dtype=float)
    wind_raw = np.nan_to_num(df["wind_ms"].to_numpy(dtype=float), nan=1.5)
    wind = wind_10m_to_2m(wind_raw) if wind_height_m >= 5.0 else np.maximum(wind_raw, 0.0)

    n = len(df)
    wet = np.zeros(n, dtype=float)

    if method == "rh85":
        wet = ((rh >= 85.0) | (rain > 0.0)).astype(float)
        return pd.Series(wet, index=df.index, name=method)

    if method == "rh90_hysteresis":
        state = False
        for i in range(n):
            if rain[i] >= RAIN_WET_MM:
                state = True
            elif not np.isfinite(rh[i]):
                state = False
            elif state:
                # Seca quando UR cai abaixo de 80 % ou radiação solar forte (> 250 W/m²)
                if rh[i] < 80.0 or (np.isfinite(rad[i]) and rad[i] > 250.0 and rh[i] < 92.0):
                    state = False
            else:
                if rh[i] >= 90.0 and (not np.isfinite(rad[i]) or rad[i] < 150.0):
                    state = True
            wet[i] = 1.0 if state else 0.0
        return pd.Series(wet, index=df.index, name=method)

    if method == "dpd_hysteresis":
        # Gillespie et al. (1993) / Gleason et al. (1994) / Sentelhas et al. (2008)
        state = False
        for i in range(n):
            if rain[i] >= RAIN_WET_MM:
                state = True
            elif not np.isfinite(dpd[i]):
                state = False
            elif state:
                if dpd[i] >= 3.8 or (np.isfinite(rad[i]) and rad[i] > 250.0 and dpd[i] >= 2.2):
                    state = False
            else:
                if dpd[i] <= 1.8:
                    state = True
            wet[i] = 1.0 if state else 0.0
        return pd.Series(wet, index=df.index, name=method)

    # method == "cart_kim2002": Kim et al. (2002), Plant Disease 86:179-185
    for i in range(n):
        if rain[i] >= RAIN_WET_MM:
            wet[i] = 1.0
            continue
        ti, rhi, dpdi, ui = t[i], rh[i], dpd[i], wind[i]
        if not (np.isfinite(ti) and np.isfinite(rhi) and np.isfinite(dpdi)):
            wet[i] = 0.0
            continue
        if dpdi >= 3.7:
            # Categoria 1: seco
            wet[i] = 0.0
        elif ui < 2.5:
            # Categoria 2: equação discriminante SLD de Kim et al. (2002)
            t_pos = max(ti, 0.0)
            score = (
                1.6064 * math.sqrt(t_pos)
                + 0.0036 * (ti ** 2)
                + 0.1531 * rhi
                - 0.4599 * ui * dpdi
                - 0.0035 * ti * rhi
            )
            wet[i] = 1.0 if score > 14.4674 else 0.0
        elif rhi >= 87.8:
            # Categoria 3: equação discriminante SLD para vento forte + UR alta
            t_pos = max(ti, 0.0)
            score = (
                0.7921 * math.sqrt(t_pos)
                + 0.0046 * (rhi ** 2)
                - 2.3889 * ui
                - 0.0390 * ti * ui
                + 1.0613 * ui * dpdi
            )
            wet[i] = 1.0 if score > 37.00 else 0.0
        else:
            # Categoria 4: seco (vento >= 2,5 m/s e UR < 87,8 %)
            wet[i] = 0.0
    return pd.Series(wet, index=df.index, name=method)


def compare_lwd_methods(weather: Any, local_tz_name: str = "America/Sao_Paulo") -> list[dict]:
    """
    Compara a distribuição diária de horas molhadas e a discriminação de dias
    com risco entre os 4 modelos de molhamento sobre a mesma série horária.
    """
    df = normalize_rich_weather(weather)
    if df.empty:
        return []
    tz = ea.ZoneInfo(local_tz_name)
    local_idx = df.index.tz_convert(tz)
    day_label = (local_idx - pd.Timedelta(hours=12)).normalize()

    rows: list[dict] = []
    for method in VALID_METHODS:
        wet = estimate_leaf_wetness(df, method=method)
        daily_lwd = wet.groupby(day_label).sum()
        # Recalcula DSV do TOM-CAST usando a estimativa de molhamento deste método
        dsv_vals = []
        for _, block in df.assign(wet=wet).groupby(day_label):
            w_blk = block[block["wet"] > 0]
            if len(w_blk) == 0:
                dsv_vals.append(0)
            else:
                dsv_vals.append(ea._lookup(ea.TOMCAST_TABLE, round(float(w_blk["temp_c"].mean())), len(w_blk)))
        dsv_arr = np.asarray(dsv_vals, dtype=float)
        rows.append({
            "method": method,
            "n_days": int(len(daily_lwd)),
            "lwd_mean_h": round(float(daily_lwd.mean()), 2),
            "lwd_sd_h": round(float(daily_lwd.std(ddof=1)), 2),
            "lwd_p50_h": round(float(daily_lwd.median()), 1),
            "lwd_p90_h": round(float(np.percentile(daily_lwd, 90)), 1),
            "dry_days_pct": round(100.0 * float((daily_lwd == 0).mean()), 1),
            "wet_days_ge6h_pct": round(100.0 * float((daily_lwd >= 6).mean()), 1),
            "tomcast_dsv_per_30d": round(float(dsv_arr.sum()) / len(dsv_arr) * 30.0, 2),
            "tomcast_days_ge2_pct": round(100.0 * float((dsv_arr >= 2).mean()), 1),
        })
    return rows


def validate_lwd_against_sensor(
    weather_with_sensor: Any,
    sensor_col: str = "leaf_wet_sensor",
    local_tz_name: str = "Europe/Luxembourg",
) -> list[dict]:
    """
    Avalia os 4 estimadores de molhamento foliar contra verdade de campo medida
    por sensor (`sensor_col` binário 0/1 ou booleano por hora).
    Retorna acurácia, POD (sensibilidade), FAR (falso alarme), F1, CSI e MAE diário (h/d).
    """
    raw = weather_with_sensor.copy() if isinstance(weather_with_sensor, pd.DataFrame) else pd.DataFrame(list(weather_with_sensor))
    if sensor_col not in raw.columns:
        raise ValueError(f"coluna de sensor '{sensor_col}' ausente")
    df = normalize_rich_weather(raw)
    if "ts" in raw.columns:
        obs_series = pd.Series(
            pd.to_numeric(raw[sensor_col], errors="coerce").to_numpy(),
            index=pd.DatetimeIndex([ea._to_utc(v) for v in raw["ts"]]),
        )
        obs_series = obs_series[~obs_series.index.duplicated(keep="last")].reindex(df.index)
    else:
        obs_series = pd.to_numeric(raw[sensor_col], errors="coerce").reindex(df.index)

    valid_mask = obs_series.notna()
    y_true = (obs_series[valid_mask].to_numpy(dtype=float) > 0.5).astype(int)
    df_valid = df.loc[valid_mask]
    tz = ea.ZoneInfo(local_tz_name)
    day_label = (df_valid.index.tz_convert(tz) - pd.Timedelta(hours=12)).normalize()
    daily_true = pd.Series(y_true, index=df_valid.index).groupby(day_label).sum()

    out: list[dict] = []
    for method in VALID_METHODS:
        y_pred = (estimate_leaf_wetness(df_valid, method=method).to_numpy(dtype=float) > 0.5).astype(int)
        tp = int(np.sum((y_pred == 1) & (y_true == 1)))
        fp = int(np.sum((y_pred == 1) & (y_true == 0)))
        fn = int(np.sum((y_pred == 0) & (y_true == 1)))
        tn = int(np.sum((y_pred == 0) & (y_true == 0)))
        acc = (tp + tn) / max(tp + fp + fn + tn, 1)
        pod = tp / max(tp + fn, 1)
        far = fp / max(tp + fp, 1)
        f1 = (2 * tp) / max(2 * tp + fp + fn, 1)
        csi = tp / max(tp + fp + fn, 1)
        daily_pred = pd.Series(y_pred, index=df_valid.index).groupby(day_label).sum()
        mae_h = float(np.mean(np.abs(daily_pred - daily_true)))
        bias_h = float(np.mean(daily_pred - daily_true))
        out.append({
            "method": method,
            "n_hours": int(len(y_true)),
            "accuracy": round(acc, 4),
            "pod": round(pod, 4),
            "far": round(far, 4),
            "f1": round(f1, 4),
            "csi": round(csi, 4),
            "daily_lwd_mae_h": round(mae_h, 3),
            "daily_lwd_bias_h": round(bias_h, 3),
        })
    return out
