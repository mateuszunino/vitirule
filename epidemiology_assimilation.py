#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
epidemiology_assimilation.py
============================
Assimila as severidades medidas por vídeo e recalibra a curva de progresso da
doença a cada nova avaliação. Substitui a taxa fixa `r_base`.

Modelo
------
A doença anda em "tempo epidemiológico" tau, não em dias de calendário:

    f_h   = g(T_h) * [d + (1 - d) * W_h]          favorabilidade da hora h, 0 a 1
    tau(t) = (1/24) * soma de f_h até t           dias favoráveis acumulados

g(T) é a resposta beta à temperatura com Tmin, Tot e Tmax do patógeno. W_h vale
1 quando UR >= 85 % ou há chuva na hora (molhamento foliar estimado). d é a
fração do progresso que continua com a folha seca, pela expansão das lesões
já instaladas. Uma aplicação de fungicida multiplica f_h por
1 - E * 0.5^((t - t_aplic) / meia_vida).

Em tau as duas curvas têm solução fechada:

    logística:  y(tau) = K / (1 + (K/y0 - 1) * exp(-r * tau))
    Gompertz:   y(tau) = K * exp(ln(y0/K) * exp(-r * tau))

r passa a ser a taxa por dia favorável. Um dia seco e frio quase não soma tau,
e a curva fica parada sem que r precise mudar. É isso que deixa a previsão de
7 dias entrar direto na projeção.

Estimação
---------
Mínimos quadrados não lineares ponderados com priori gaussiana, que é a
estimativa MAP. Parâmetros theta = [ln r, logit(y0/K)], mais logit de K quando
`fit_K=True`. Resíduos empilhados:

    (y_i - y_hat_i) / sigma_i        dados
    (theta_j - mu_j) / s_j           priori

    sigma_i² = [sigma_piso² + (cv * y_hat_i)² + sd_vídeo_i²] / lambda^(idade_i em dias)

O termo proporcional acompanha o erro de segmentação, que cresce com a
severidade. `sd_vídeo` é o desvio entre keyframes vindo de vision_pipeline.
lambda < 1 dá mais peso às avaliações recentes, para r acompanhar mudança de
regime. A perda soft-L1 limita o efeito de um vídeo ruim. A priori segura r
quando há duas ou três avaliações, fase em que r e y0 não se separam só pelos
dados.

A incerteza parte de (J'J)^-1 no ótimo, que é a aproximação de Laplace,
inflada pelo qui-quadrado reduzido quando ele passa de 1. Essa gaussiana é
estreita demais quando r e y0 se compensam, o que acontece com poucas
avaliações ou com a severidade ainda dentro do ruído. Por isso ela serve só de
proposta para uma reamostragem por importância com t de Student, que devolve
amostras da posteriori de fato. Leitura igual a zero entra como censurada à
esquerda (Tobit).

Por que não um filtro de Kalman estendido: com 2 a 20 avaliações por unidade,
refazer o ajuste com o histórico inteiro custa milissegundos e não acumula
erro de linearização. O que o EKF traria, a inovação da nova medida, é
calculado aqui: prevê-se a avaliação nova com o ajuste anterior e, se |z| > 3,
o ajuste é refeito com esquecimento rápido e marcado como `regime_change`.

Projeção e IC 95 %
------------------
Monte Carlo sobre as amostras da posteriori. A incerteza da previsão do tempo
entra como fator lognormal nos incrementos futuros de tau, com desvio que
cresce com o horizonte. Os percentis 2,5, 50 e 97,5 das trajetórias formam a
faixa, que respeita 0 <= y <= K por construção.

AACPD
-----
Regra dos trapézios, a mesma de agricolae::audpc e epifitter::AUDPC no R, em
% x dia. A parte observada usa os dados. A projetada é calculada em cada
trajetória simulada e sai com mediana e IC 95 %.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.special import expit, log_ndtr, logit

log = logging.getLogger("epidemiology_assimilation")

SCHEMA_VERSION = "1.0"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

# Valores iniciais de literatura. Recalibrar com a testemunha (V01-V10) ao fim do ensaio.
PATHOGENS: dict[str, dict[str, float]] = {
    "pinta_preta": {   # Alternaria solani
        "tmin": 6.0, "topt": 27.0, "tmax": 35.0, "dry_factor": 0.25,
        "r_prior": 0.18, "r_prior_gompertz": 0.10, "r_prior_sd_log": 0.70, "y0_prior_pct": 0.20,
    },
    "requeima": {      # Phytophthora infestans
        "tmin": 4.0, "topt": 20.0, "tmax": 30.0, "dry_factor": 0.10,
        "r_prior": 0.35, "r_prior_gompertz": 0.19, "r_prior_sd_log": 0.70, "y0_prior_pct": 0.20,
    },
}

# TOM-CAST (Pitblado 1992; tabela de Madden et al. 1978): horas de molhamento
# para DSV 1, 2, 3 e 4 por faixa de temperatura média do período molhado.
TOMCAST_TABLE = [
    (13, 17, (7, 16, 21, None)),
    (18, 20, (4, 9, 16, 23)),
    (21, 25, (3, 6, 13, 21)),
    (26, 29, (4, 9, 16, 23)),
]
# Wallin (base do BLITECAST): horas seguidas de UR alta para valores 1 a 4.
WALLIN_TABLE = [
    (7.2, 11.6, (16, 19, 22, None)),
    (11.7, 15.0, (13, 16, 19, 22)),
    (15.1, 26.6, (10, 13, 16, 19)),
]


@dataclass
class AssimilationConfig:
    model: str = "auto"                 # "auto" | "logistic" | "gompertz"
    K: float = 100.0                    # assíntota em %, fixa por padrão
    fit_K: bool = False
    rh_wet_threshold: float = 85.0
    sigma_floor: float = 0.30           # pontos percentuais
    sigma_cv: float = 0.10
    forgetting: float = 0.97            # peso por dia de idade da observação
    forgetting_fast: float = 0.80       # usado depois de mudança de regime
    innovation_z: float = 3.0
    robust_scale: float = 2.0           # f_scale da perda soft-L1, em sigmas
    y0_prior_sd_logit: float = 2.5
    horizon_hours: int = 168
    output_step_hours: int = 6
    n_draws: int = 4000
    fc_sigma0: float = 0.05             # incerteza relativa de tau já na 1ª hora
    fc_sigma_per_day: float = 0.03      # acréscimo por dia de horizonte
    spray_efficacy: float = 0.60
    spray_half_life_days: float = 7.0
    action_threshold_pct: float = 5.0
    detection_floor_pct: float = 0.05
    seed: int = 20261118


# --------------------------------------------------------------------------
# Clima -> tempo epidemiológico
# --------------------------------------------------------------------------
def beta_temperature_response(temp_c, tmin: float, topt: float, tmax: float) -> np.ndarray:
    """Resposta beta (Yan e Hunt, 1999): 0 fora de [Tmin, Tmax] e 1 em Tot."""
    t = np.asarray(temp_c, dtype=float)
    out = np.zeros_like(t)
    ok = (t > tmin) & (t < tmax)
    alpha = (topt - tmin) / (tmax - topt)
    out[ok] = ((tmax - t[ok]) / (tmax - topt)) * ((t[ok] - tmin) / (topt - tmin)) ** alpha
    return np.clip(out, 0.0, 1.0)


def _to_utc(ts: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        raise ValueError(f"timestamp sem fuso: {ts!r}. Use ISO 8601 com offset.")
    return stamp.tz_convert("UTC")


_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _epoch_seconds(stamps: Any) -> np.ndarray:
    """Segundos desde 1970 em float. Não depende da resolução interna do pandas (ns, us ou s)."""
    index = pd.DatetimeIndex(stamps)
    return np.asarray((index - _EPOCH) / pd.Timedelta(seconds=1), dtype=float)


def weather_frame(records: Any) -> pd.DataFrame:
    """Normaliza registros horários para um DataFrame indexado em UTC."""
    cols = ["temp_c", "rh_pct", "precip_mm"]
    if records is None:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    df = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(list(records))
    if df.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    if "ts" in df.columns:
        df.index = pd.DatetimeIndex([_to_utc(v) for v in df["ts"]])
    elif df.index.tz is None:
        raise ValueError("clima sem coluna 'ts' e com índice sem fuso")
    else:
        df.index = df.index.tz_convert("UTC")
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else np.nan
    df = df[cols].sort_index()
    return df[~df.index.duplicated(keep="last")]


def merge_weather(observed: Any, forecast: Any) -> pd.DataFrame:
    """Junta observado e previsto. Onde os dois existem, vale o observado."""
    obs, fc = weather_frame(observed), weather_frame(forecast)
    if obs.empty:
        return fc
    if fc.empty:
        return obs
    return pd.concat([fc[~fc.index.isin(obs.index)], obs]).sort_index()


def leaf_wetness(df: pd.DataFrame, rh_threshold: float = 85.0) -> pd.Series:
    """Molhamento estimado: UR >= limiar ou chuva na hora."""
    return ((df["rh_pct"] >= rh_threshold) | (df["precip_mm"].fillna(0) > 0)).astype(float)


@dataclass
class EpiClock:
    """Converte instantes em tau a partir de uma grade horária de favorabilidade."""
    grid: pd.DatetimeIndex            # limites de hora em UTC; f[k] vale em (grid[k-1], grid[k]]
    cumulative: np.ndarray            # tau acumulado em cada limite, em dias favoráveis
    favorability: np.ndarray
    gap_hours: int
    has_weather: bool

    def tau(self, ts: Any) -> np.ndarray:
        stamps = [_to_utc(t) for t in (ts if isinstance(ts, (list, tuple, pd.Series, pd.Index, np.ndarray)) else [ts])]
        return np.interp(_epoch_seconds(stamps), _epoch_seconds(self.grid), self.cumulative)


def build_clock(weather: pd.DataFrame, start: Any, end: Any, disease: str,
                cfg: AssimilationConfig, spray_events: Sequence[Any] = ()) -> EpiClock:
    """
    Monta tau(t) entre `start` e `end`. Sem clima algum, f = 1 e tau vira dia
    de calendário. Falhas de até 3 h são interpoladas. As maiores recebem a
    média da mesma hora do dia.
    """
    params = PATHOGENS[disease]
    t0 = _to_utc(start).floor("h")
    t1 = _to_utc(end).ceil("h")
    grid = pd.date_range(t0, t1, freq="h", tz="UTC")
    n = len(grid) - 1
    if weather.empty:
        fav = np.ones(n)
        gaps, has = 0, False
    else:
        hourly = weather.reindex(grid[1:])
        missing = hourly[["temp_c", "rh_pct"]].isna().any(axis=1)
        gaps = int(missing.sum())
        hourly[["temp_c", "rh_pct"]] = hourly[["temp_c", "rh_pct"]].interpolate(
            method="time", limit=3, limit_area="inside")
        still = hourly[["temp_c", "rh_pct"]].isna().any(axis=1)
        if still.any():
            by_hour = weather.groupby(weather.index.hour)[["temp_c", "rh_pct"]].mean()
            overall = weather[["temp_c", "rh_pct"]].mean()
            for col in ("temp_c", "rh_pct"):
                fill = hourly.index.hour.map(by_hour[col]).to_numpy(dtype=float)
                fill = np.where(np.isnan(fill), overall[col], fill)
                hourly[col] = hourly[col].where(~hourly[col].isna(), fill)
        g = beta_temperature_response(hourly["temp_c"].to_numpy(), params["tmin"],
                                      params["topt"], params["tmax"])
        wet = leaf_wetness(hourly, cfg.rh_wet_threshold).to_numpy()
        fav = g * (params["dry_factor"] + (1.0 - params["dry_factor"]) * wet)
        fav = np.nan_to_num(fav, nan=float(np.nanmean(fav)) if np.isfinite(fav).any() else 0.5)
        has = True

    if spray_events:
        hours = _epoch_seconds(grid[1:])
        protection = np.zeros(n)
        for event in spray_events:
            age_days = (hours - _epoch_seconds([_to_utc(event)])[0]) / 86_400.0
            effect = np.where(age_days >= 0,
                              cfg.spray_efficacy * 0.5 ** (age_days / cfg.spray_half_life_days), 0.0)
            protection = np.maximum(protection, effect)
        fav = fav * (1.0 - protection)

    cumulative = np.concatenate([[0.0], np.cumsum(fav) / 24.0])
    return EpiClock(grid=grid, cumulative=cumulative, favorability=fav, gap_hours=gaps, has_weather=has)


# --------------------------------------------------------------------------
# Curvas e parametrização
# --------------------------------------------------------------------------
def curve(model: str, tau, r, y0, K):
    tau = np.asarray(tau, dtype=float)
    if model == "logistic":
        return K / (1.0 + (K / y0 - 1.0) * np.exp(-r * tau))
    if model == "gompertz":
        return K * np.exp(np.log(y0 / K) * np.exp(-r * tau))
    raise ValueError(f"modelo desconhecido: {model}")


def _unpack(theta: np.ndarray, K_fixed: float, k_floor: Optional[float]):
    r = np.exp(theta[..., 0])
    if k_floor is None:
        K = np.full_like(r, K_fixed) if np.ndim(r) else K_fixed
    else:
        K = k_floor + (100.0 - k_floor) * expit(theta[..., 2])
    y0 = K * np.clip(expit(theta[..., 1]), 1e-7, 1 - 1e-7)
    return r, y0, K


@dataclass
class FitResult:
    model: str
    theta: np.ndarray
    cov: np.ndarray
    k_floor: Optional[float]
    chi2: float
    n: int
    sigma: np.ndarray
    yhat: np.ndarray
    draws: np.ndarray = field(repr=False, default=None)   # amostras da posteriori, (N, p)
    ess: float = 0.0                                      # tamanho efetivo da amostra

    @property
    def p(self) -> int:
        return len(self.theta)

    @property
    def aicc(self) -> float:
        k, n = self.p, self.n
        correction = (2 * k * (k + 1)) / (n - k - 1) if n - k - 1 > 0 else float("inf")
        return self.chi2 + 2 * k + correction

    @property
    def chi2_red(self) -> float:
        return self.chi2 / max(self.n - self.p, 1)


def _fit_model(model: str, tau: np.ndarray, y: np.ndarray, sd_video: np.ndarray,
               age_days: np.ndarray, prior_mu: np.ndarray, prior_sd: np.ndarray,
               cfg: AssimilationConfig, forgetting: float,
               warm_start: Optional[np.ndarray], rng: np.random.Generator) -> FitResult:
    k_floor = min(1.05 * float(np.max(y)) + 0.5, 99.0) if cfg.fit_K else None
    weight = np.maximum(forgetting ** age_days, 1e-3)

    def sigma_of(level: np.ndarray) -> np.ndarray:
        var = cfg.sigma_floor ** 2 + (cfg.sigma_cv * level) ** 2 + sd_video ** 2
        return np.sqrt(var / weight)

    def predict(theta: np.ndarray) -> np.ndarray:
        r, y0, K = _unpack(theta, cfg.K, k_floor)
        return curve(model, tau, r, y0, K)

    censored = y <= 0.0

    def data_residuals(theta: np.ndarray, sigma: np.ndarray) -> np.ndarray:
        """
        Resíduo gaussiano para y > 0. Para y = 0 a medida é censurada à esquerda
        (Tobit): a contribuição é -log Phi(-y_hat/sigma), escrita como resíduo
        cuja metade do quadrado dá essa parcela. Sem isso o ruído truncado em
        zero puxa a curva para cima quando a severidade ainda é baixa.
        """
        z = (y - predict(theta)) / sigma
        if censored.any():
            z = z.copy()
            z[censored] = np.sqrt(np.maximum(-2.0 * log_ndtr(z[censored]), 0.0))
        return z

    def make_residuals(sigma: np.ndarray):
        def residuals(theta: np.ndarray) -> np.ndarray:
            return np.concatenate([data_residuals(theta, sigma), (theta - prior_mu) / prior_sd])
        return residuals

    starts = [prior_mu.copy()]
    if warm_start is not None and len(warm_start) == len(prior_mu):
        starts.append(np.asarray(warm_start, dtype=float))
    positive = y > cfg.detection_floor_pct
    if positive.sum() >= 2 and np.ptp(tau[positive]) > 0:   # chute pela forma linearizada
        K0 = cfg.K if k_floor is None else 0.5 * (k_floor + 100.0)
        frac = np.clip(y[positive] / K0, 1e-6, 1 - 1e-6)
        z = logit(frac) if model == "logistic" else -np.log(-np.log(frac))
        slope, intercept = np.polyfit(tau[positive], z, 1)
        if slope > 0:
            y0_frac = expit(intercept) if model == "logistic" else math.exp(-math.exp(-intercept))
            guess = prior_mu.copy()
            guess[0] = math.log(slope)
            guess[1] = logit(min(max(y0_frac, 1e-6), 1 - 1e-6))
            starts.append(guess)

    sigma = sigma_of(np.maximum(y, 0.0))
    best = None
    for _ in range(2):   # segunda volta com sigma calculado a partir do ajustado
        fun = make_residuals(sigma)
        candidates = [least_squares(fun, s, loss="soft_l1", f_scale=cfg.robust_scale,
                                    x_scale="jac", max_nfev=400) for s in starts]
        best = min(candidates, key=lambda sol: sol.cost)
        starts = [best.x]
        sigma = sigma_of(np.maximum(predict(best.x), 0.0))

    yhat = predict(best.x)
    chi2 = float(np.sum(data_residuals(best.x, sigma) ** 2))
    jac = best.jac
    inflation = max(1.0, chi2 / max(len(y) - len(best.x), 1))
    laplace = np.linalg.pinv(jac.T @ jac) * inflation
    laplace = 0.5 * (laplace + laplace.T) + 1e-10 * np.eye(len(best.x))

    def log_posterior(thetas: np.ndarray) -> np.ndarray:
        """Log-posteriori (a menos de constante) com a mesma perda soft-L1 do ajuste."""
        r, y0, K = _unpack(thetas, cfg.K, k_floor)
        pred = curve(model, tau[None, :], r[:, None], y0[:, None], K[:, None])
        z = (y[None, :] - pred) / sigma[None, :]
        if censored.any():
            z[:, censored] = np.sqrt(np.maximum(-2.0 * log_ndtr(z[:, censored]), 0.0))
        scale = cfg.robust_scale
        rho = lambda f: 2.0 * (np.sqrt(1.0 + (f / scale) ** 2) - 1.0)
        data = -0.5 * scale ** 2 * rho(z).sum(axis=1) / inflation
        prior = -0.5 * scale ** 2 * rho((thetas - prior_mu) / prior_sd).sum(axis=1)
        return data + prior

    draws, cov, ess = _importance_resample(log_posterior, best.x, laplace, rng, cfg.n_draws)
    return FitResult(model=model, theta=best.x, cov=cov, k_floor=k_floor, chi2=chi2,
                     n=len(y), sigma=sigma, yhat=yhat, draws=draws, ess=ess)


def _importance_resample(log_posterior, center: np.ndarray, cov: np.ndarray,
                         rng: np.random.Generator, n: int, dof: float = 4.0):
    """
    Corrige a aproximação de Laplace. Com poucas avaliações, ou com a severidade
    ainda abaixo do ruído de medida, r e y0 se compensam e a posteriori fica em
    forma de banana, que a gaussiana no ótimo estreita demais. Proposta: t de
    Student multivariada com caudas largas. Duas voltas, a segunda recentrada
    na média e na covariância ponderadas da primeira. Devolve amostras
    reamostradas pelos pesos, a covariância ponderada e o tamanho efetivo.
    """
    p = len(center)
    mean, sigma, widen = center.copy(), cov.copy(), 4.0
    theta = weights = None
    for _ in range(2):
        scale_cov = widen * sigma + 1e-10 * np.eye(p)
        chol = np.linalg.cholesky(scale_cov)
        z = rng.standard_normal((n, p)) @ chol.T
        u = rng.chisquare(dof, size=n) / dof
        theta = mean + z / np.sqrt(u)[:, None]
        delta = theta - mean
        maha = np.einsum("ij,jk,ik->i", delta, np.linalg.inv(scale_cov), delta)
        log_q = -0.5 * (dof + p) * np.log1p(maha / dof)
        log_w = log_posterior(theta) - log_q
        log_w = np.where(np.isfinite(log_w), log_w, -np.inf)
        weights = np.exp(log_w - log_w.max())
        weights /= weights.sum()
        mean = weights @ theta
        centered = theta - mean
        sigma = (centered * weights[:, None]).T @ centered
        sigma = 0.5 * (sigma + sigma.T)
        widen = 2.0
    ess = float(1.0 / np.sum(weights ** 2))
    picked = rng.choice(n, size=n, replace=True, p=weights)
    return theta[picked], sigma + 1e-12 * np.eye(p), ess


# --------------------------------------------------------------------------
# AACPD e índices de risco
# --------------------------------------------------------------------------
def aacpd(times: Sequence[Any], severity_pct: Sequence[float]) -> float:
    """Área abaixo da curva de progresso da doença, por trapézios, em % x dia."""
    seconds = _epoch_seconds([_to_utc(t) for t in times])
    days = (seconds - seconds[0]) / 86_400.0
    y = np.asarray(severity_pct, dtype=float)
    return float(np.sum(np.diff(days) * (y[:-1] + y[1:]) / 2.0))


def _daily_windows(df: pd.DataFrame, day_start_hour: int):
    """Janelas de 24 h em horário local, começando em `day_start_hour`."""
    local = df.tz_convert(LOCAL_TZ)
    label = (local.index - pd.Timedelta(hours=day_start_hour)).normalize()
    return local.groupby(label)


def _lookup(table, temp: float, hours: float) -> int:
    for lo, hi, limits in table:
        if lo <= temp <= hi:
            value = 0
            for level, limit in enumerate(limits, start=1):
                if limit is not None and hours >= limit:
                    value = level
            return value
    return 0


def tomcast_dsv(weather: Any, rh_threshold: float = 85.0, day_start_hour: int = 12) -> pd.Series:
    """
    DSV diário do TOM-CAST. A janela vai de 12 h a 12 h locais para não partir
    o orvalho de uma noite em dois dias. A temperatura é a média das horas
    molhadas, arredondada ao inteiro. Fora de 13 a 29 graus o DSV é 0.
    """
    df = weather_frame(weather)
    if df.empty:
        return pd.Series(dtype=int)
    df = df.assign(wet=leaf_wetness(df, rh_threshold))
    out = {}
    for day, block in _daily_windows(df, day_start_hour):
        wet = block[block["wet"] > 0]
        hours = len(wet)
        out[day.date().isoformat()] = _lookup(TOMCAST_TABLE, round(float(wet["temp_c"].mean())), hours) if hours else 0
    return pd.Series(out, dtype=int)


def wallin_severity(weather: Any, rh_threshold: float = 90.0, day_start_hour: int = 12) -> pd.Series:
    """
    Valores de severidade de Wallin para requeima: maior sequência de horas
    com UR >= limiar na janela diária e temperatura média nessas horas.
    """
    df = weather_frame(weather)
    if df.empty:
        return pd.Series(dtype=int)
    out = {}
    for day, block in _daily_windows(df, day_start_hour):
        humid = (block["rh_pct"] >= rh_threshold).to_numpy()
        best_len, best_end, run = 0, -1, 0
        for i, flag in enumerate(humid):
            run = run + 1 if flag else 0
            if run > best_len:
                best_len, best_end = run, i
        if best_len == 0:
            out[day.date().isoformat()] = 0
            continue
        temp = float(block["temp_c"].iloc[best_end - best_len + 1: best_end + 1].mean())
        out[day.date().isoformat()] = _lookup(WALLIN_TABLE, round(temp, 1), best_len)
    return pd.Series(out, dtype=int)


def aggregate_leaves_to_pot(assessments: Sequence[dict]) -> list[dict]:
    """
    Reduz as folhas de um vaso a uma observação por data local. O vaso é a
    unidade experimental e as folhas são subamostras. O desvio devolvido é o
    erro-padrão da média entre folhas somado ao erro médio de vídeo.
    """
    df = pd.DataFrame(list(assessments))
    df["ts"] = [_to_utc(v) for v in df["ts"]]
    df["day"] = df["ts"].dt.tz_convert(LOCAL_TZ).dt.date
    if "severity_sd_pct" not in df.columns:
        df["severity_sd_pct"] = np.nan
    rows = []
    for _, block in df.groupby("day"):
        n = len(block)
        between = float(block["severity_pct"].std(ddof=1)) if n > 1 else 0.0
        within = float(np.sqrt(np.nanmean(block["severity_sd_pct"].fillna(0.0) ** 2)))
        rows.append({"ts": block["ts"].mean().isoformat(),
                     "severity_pct": float(block["severity_pct"].mean()),
                     "severity_sd_pct": float(np.sqrt((between ** 2 + within ** 2) / n)),
                     "n_leaves": n})
    return rows


def prior_from_population(fits: Sequence[dict]) -> Optional[dict]:
    """Priori empírica de r a partir dos ajustes de outras unidades do mesmo tratamento."""
    rates = np.array([f["params"]["r"] for f in fits if f.get("params", {}).get("r")], dtype=float)
    if rates.size < 3:
        return None
    logs = np.log(rates)
    return {"r_prior": float(np.exp(logs.mean())), "r_prior_sd_log": float(max(logs.std(ddof=1), 0.25))}


# --------------------------------------------------------------------------
# Assimilação
# --------------------------------------------------------------------------
def assimilate(unit_id: str, disease: str, observations: Sequence[dict],
               weather_observed: Any = None, weather_forecast: Any = None,
               prev_state: Optional[dict] = None, spray_events: Sequence[Any] = (),
               prior: Optional[dict] = None, config: Optional[AssimilationConfig] = None,
               now: Any = None) -> dict:
    """
    Reajusta a curva com todas as observações da unidade e projeta o horizonte.

    observations: [{"ts": ISO 8601 com fuso, "severity_pct": float, "severity_sd_pct": float|None}]
    weather_*:    [{"ts", "temp_c", "rh_pct", "precip_mm"}] horários, `ts` no fim da hora
    prev_state:   campo "state" devolvido na chamada anterior da mesma unidade
    prior:        {"r_prior", "r_prior_sd_log", "y0_prior_pct"} para trocar o padrão
    """
    cfg = config or AssimilationConfig()
    if disease not in PATHOGENS:
        raise ValueError(f"doença desconhecida: {disease}. Use {sorted(PATHOGENS)}")
    if not observations:
        raise ValueError("é preciso ao menos uma observação")
    flags: list[str] = []
    params = {**PATHOGENS[disease], **(prior or {})}

    obs = pd.DataFrame(list(observations))
    obs["ts"] = [_to_utc(v) for v in obs["ts"]]
    obs = obs.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    y = obs["severity_pct"].to_numpy(dtype=float)
    if np.any((y < 0) | (y > 100)) or np.any(~np.isfinite(y)):
        raise ValueError("severity_pct fora de 0 a 100")
    sd_video = (pd.to_numeric(obs["severity_sd_pct"], errors="coerce").fillna(0.0).to_numpy()
                if "severity_sd_pct" in obs.columns else np.zeros(len(y)))

    t_first, t_last = obs["ts"].iloc[0], obs["ts"].iloc[-1]
    t_end = t_last + pd.Timedelta(hours=cfg.horizon_hours)
    weather = merge_weather(weather_observed, weather_forecast)
    clock = build_clock(weather, t_first, t_end, disease, cfg, spray_events)
    if not clock.has_weather:
        flags.append("no_weather_calendar_time")
    elif clock.gap_hours:
        flags.append("weather_gaps_filled")
    forecast_end = weather.index.max() if not weather.empty else None
    if forecast_end is None or forecast_end < t_end - pd.Timedelta(hours=1):
        flags.append("forecast_shorter_than_horizon")

    tau_obs = clock.tau(obs["ts"])
    age_days = ((t_last - obs["ts"]).dt.total_seconds() / 86_400.0).to_numpy()
    if float(np.max(y)) < cfg.detection_floor_pct:
        flags.append("pre_symptomatic")

    y0_frac = min(max(params["y0_prior_pct"] / cfg.K, 1e-6), 0.5)
    r_prior_by_model = {
        "logistic": float(params["r_prior"]),
        "gompertz": float(params.get("r_prior_gompertz", 0.55 * params["r_prior"])),
    }

    def _prior_mu_for(model_name: str) -> np.ndarray:
        mu = [math.log(r_prior_by_model[model_name]), float(logit(y0_frac))]
        if cfg.fit_K:
            mu.append(2.0)       # priori fraca empurrando K para perto de 100 %
        return np.array(mu)

    prior_sd_list = [params["r_prior_sd_log"], cfg.y0_prior_sd_logit]
    if cfg.fit_K:
        prior_sd_list.append(2.0)
    prior_sd = np.array(prior_sd_list)

    warm = np.array(prev_state["theta"]) if prev_state and prev_state.get("theta") else None
    models = ["logistic", "gompertz"] if cfg.model == "auto" else [cfg.model]
    rng = np.random.default_rng(cfg.seed)

    def run_fits(forgetting: float, upto: Optional[int] = None) -> dict[str, FitResult]:
        sl = slice(0, upto)
        ages = age_days[sl] - (age_days[sl].min() if upto else 0.0)
        return {m: _fit_model(m, tau_obs[sl], y[sl], sd_video[sl], ages, _prior_mu_for(m), prior_sd,
                              cfg, forgetting,
                              warm if prev_state and prev_state.get("model") == m else None, rng)
                for m in models}

    def choose(fits: dict[str, FitResult]) -> FitResult:
        if len(fits) == 1:
            return next(iter(fits.values()))
        if len(y) < 5:             # poucos pontos não distinguem as duas formas
            return fits["logistic"]
        return min(fits.values(), key=lambda f: f.aicc)

    # Inovação: a avaliação mais recente prevista pelo ajuste anterior
    innovation = None
    reference: Optional[tuple[str, np.ndarray, Optional[float]]] = None
    if (prev_state and prev_state.get("mean") and prev_state.get("cov")
            and _to_utc(prev_state["last_obs_ts"]) < t_last
            and _to_utc(prev_state.get("t0", t_first)) == t_first):
        ref_draws = rng.multivariate_normal(np.array(prev_state["mean"]),
                                            np.array(prev_state["cov"]), size=2000)
        reference = (prev_state["model"], ref_draws, prev_state.get("k_floor"))
    elif len(y) >= 4:
        held = choose(run_fits(cfg.forgetting, upto=len(y) - 1))
        reference = (held.model, held.draws, held.k_floor)
    if reference is not None:
        ref_model, draws, ref_floor = reference
        r_d, y0_d, K_d = _unpack(draws, cfg.K, ref_floor)
        pred = curve(ref_model, tau_obs[-1], r_d, y0_d, K_d)
        center = float(np.median(pred))
        obs_var = cfg.sigma_floor ** 2 + (cfg.sigma_cv * center) ** 2 + sd_video[-1] ** 2
        pred_sd = math.sqrt(float(np.var(pred)) + obs_var)
        z = (y[-1] - center) / pred_sd
        innovation = {"predicted_pct": round(center, 4), "observed_pct": round(float(y[-1]), 4),
                      "pred_sd_pct": round(pred_sd, 4), "z": round(float(z), 3),
                      "regime_change": bool(abs(z) > cfg.innovation_z)}

    forgetting = cfg.forgetting
    if innovation and innovation["regime_change"]:
        forgetting = cfg.forgetting_fast
        flags.append("regime_change")
    fits = run_fits(forgetting)
    fit = choose(fits)
    if len(y) < 3:
        flags.append("prior_dominated")

    # ---- projeção por Monte Carlo ------------------------------------------
    draws = fit.draws
    r_d, y0_d, K_d = _unpack(draws, cfg.K, fit.k_floor)
    K_col = K_d[:, None]
    if fit.ess < 0.05 * cfg.n_draws:
        flags.append("posterior_low_ess")
    future = pd.date_range(t_last, t_end, freq="h", tz="UTC")
    tau_future = clock.tau(future)
    increments = np.diff(tau_future)
    lead_days = np.arange(1, len(future)) / 24.0
    sigma_w = cfg.fc_sigma0 + cfg.fc_sigma_per_day * lead_days
    if not clock.has_weather:
        sigma_w = np.zeros_like(sigma_w)
    shock = rng.standard_normal(cfg.n_draws)[:, None]
    factor = np.exp(shock * sigma_w[None, :] - 0.5 * sigma_w[None, :] ** 2)
    tau_draws = tau_future[0] + np.concatenate(
        [np.zeros((cfg.n_draws, 1)), np.cumsum(increments[None, :] * factor, axis=1)], axis=1)
    traj = curve(fit.model, tau_draws, r_d[:, None], y0_d[:, None], K_col)
    q_lo, q_med, q_hi = np.percentile(traj, [2.5, 50.0, 97.5], axis=0)

    step = cfg.output_step_hours
    projection = [{"ts": future[i].tz_convert(LOCAL_TZ).isoformat(), "lead_h": int(i),
                   "tau": round(float(tau_future[i]), 4), "y_median": round(float(q_med[i]), 4),
                   "y_lo95": round(float(q_lo[i]), 4), "y_hi95": round(float(q_hi[i]), 4)}
                  for i in range(0, len(future), step)]

    # ---- AACPD ---------------------------------------------------------------
    area_obs = aacpd(obs["ts"], y) if len(y) > 1 else 0.0
    area_proj = np.sum((traj[:, :-1] + traj[:, 1:]) / 2.0, axis=1) / 24.0
    proj_q = np.percentile(area_proj, [2.5, 50.0, 97.5])
    total_days = (t_end - t_first).total_seconds() / 86_400.0
    area = {
        "unit": "pct_x_dia",
        "observed": round(area_obs, 3),
        "projected_median": round(float(proj_q[1]), 3),
        "projected_ci95": [round(float(proj_q[0]), 3), round(float(proj_q[2]), 3)],
        "total_median": round(area_obs + float(proj_q[1]), 3),
        "total_ci95": [round(area_obs + float(proj_q[0]), 3), round(area_obs + float(proj_q[2]), 3)],
        "relative_total": round((area_obs + float(proj_q[1])) / (100.0 * total_days), 5),
        "window_days": round(total_days, 3),
    }

    # ---- risco climático no horizonte ---------------------------------------
    fc_window = weather[(weather.index > t_last) & (weather.index <= t_end)]
    risk = {
        "wet_hours_7d": int(leaf_wetness(fc_window, cfg.rh_wet_threshold).sum()) if not fc_window.empty else None,
        "tomcast_dsv_7d": int(tomcast_dsv(fc_window, cfg.rh_wet_threshold).sum()) if not fc_window.empty else None,
        "wallin_sv_7d": int(wallin_severity(fc_window).sum()) if not fc_window.empty else None,
        "tau_gain_7d": round(float(tau_future[-1] - tau_future[0]), 4),
        "p_exceed": {"threshold_pct": cfg.action_threshold_pct,
                     "p": round(float(np.mean(traj[:, -1] >= cfg.action_threshold_pct)), 4)},
    }

    r_hat, y0_hat, K_hat = _unpack(fit.theta, cfg.K, fit.k_floor)
    r_ci = np.percentile(r_d, [2.5, 97.5])
    residual = y - fit.yhat
    result = {
        "schema_version": SCHEMA_VERSION,
        "unit_id": unit_id, "disease": disease,
        "fitted_at": (_to_utc(now) if now else pd.Timestamp.now(tz="UTC")).tz_convert(LOCAL_TZ).isoformat(),
        "model": fit.model, "n_obs": int(len(y)),
        "params": {"r": round(float(r_hat), 6),
                   "r_ci95": [round(float(r_ci[0]), 6), round(float(r_ci[1]), 6)],
                   "r_unit": "por_dia_favoravel" if clock.has_weather else "por_dia",
                   "y0_pct": round(float(y0_hat), 6), "K_pct": round(float(K_hat), 4),
                   "r_prior": r_prior_by_model[fit.model], "r_prior_sd_log": params["r_prior_sd_log"]},
        "fit": {"rmse_pct": round(float(np.sqrt(np.mean(residual ** 2))), 4),
                "chi2_red": round(fit.chi2_red, 4),
                "aicc": {m: (round(f.aicc, 3) if math.isfinite(f.aicc) else None) for m, f in fits.items()},
                "forgetting": forgetting, "posterior_ess": round(fit.ess, 1),
                "fitted_pct": [round(float(v), 4) for v in fit.yhat]},
        "innovation": innovation,
        "tau": {"at_last_obs": round(float(tau_obs[-1]), 4),
                "calendar_days": round(float(age_days[0]), 3),
                "weather_gap_hours": clock.gap_hours},
        "projection": projection,
        "aacpd": area,
        "risk": risk,
        "state": {"model": fit.model, "theta": [float(v) for v in fit.theta],
                  "mean": [float(v) for v in draws.mean(axis=0)],
                  "cov": [[float(v) for v in row] for row in fit.cov],
                  "k_floor": fit.k_floor, "t0": t_first.isoformat(),
                  "last_obs_ts": t_last.isoformat()},
        "flags": sorted(set(flags)),
    }
    return result


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def _demo_payload() -> dict:
    """Epidemia sintética de pinta-preta com clima alternando noites úmidas e dias secos."""
    rng = np.random.default_rng(3)
    start = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    hours = [start + timedelta(hours=h) for h in range(1, 24 * 23 + 1)]
    weather = []
    for i, ts in enumerate(hours):
        local_hour = (ts.hour - 3) % 24
        temp = 23 + 5 * math.sin((local_hour - 9) / 24 * 2 * math.pi) + rng.normal(0, 0.6)
        rh = 78 - 16 * math.sin((local_hour - 9) / 24 * 2 * math.pi) + rng.normal(0, 3)
        rain = float(rng.random() < 0.06) * rng.gamma(2.0, 1.5)
        weather.append({"ts": ts.isoformat(), "temp_c": round(temp, 2),
                        "rh_pct": round(min(rh + (12 if rain else 0), 100), 1), "precip_mm": round(rain, 2)})
    cfg = AssimilationConfig()
    clock = build_clock(weather_frame(weather), start, hours[-1], "pinta_preta", cfg)
    obs = []
    for day in range(0, 15, 2):
        ts = start + timedelta(days=day)
        truth = float(curve("logistic", clock.tau(ts)[0], 0.55, 0.4, 100.0))
        obs.append({"ts": ts.isoformat(),
                    "severity_pct": round(max(truth * (1 + rng.normal(0, 0.08)) + rng.normal(0, 0.15), 0), 3),
                    "severity_sd_pct": 0.2})
    cut = start + timedelta(days=14)
    return {"unit_id": "V03", "disease": "pinta_preta", "observations": obs,
            "weather_observed": [w for w in weather if datetime.fromisoformat(w["ts"]) <= cut],
            "weather_forecast": [w for w in weather if datetime.fromisoformat(w["ts"]) > cut]}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Assimilação de severidade e projeção de 7 dias.")
    parser.add_argument("--input", help="JSON com unit_id, disease, observations, weather_*, prev_state, spray_events")
    parser.add_argument("--output")
    parser.add_argument("--demo", action="store_true", help="roda um exemplo sintético")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.demo:
        payload = _demo_payload()
    elif args.input:
        with open(args.input, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        parser.error("informe --input ou --demo")
    cfg = replace(AssimilationConfig(), **payload.pop("config", {}))
    result = assimilate(config=cfg, **payload)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
