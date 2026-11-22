"""
vitirule_v2.lwd
===============
Estimadores puros de molhamento foliar horario (biblioteca padrao Python,
compativel com Pyodide, sem dependencia da v1 e sem ler o sensor fisico).

Hierarquia pre-registrada em `docs/v2/preregistro.md` (Secao 6):
- Estimador primario:
  * `rh90_rain`: UR >= 90% ou precipitacao > 0 mm/h.
- Estimadores secundarios (parametros publicados fixos, sem ajuste local):
  * `dpd_hysteresis`: depressao do ponto de orvalho DPD = T - Td com histerese
    (inicio <= 1,8 C, secagem >= 3,8 C; Gillespie, Srivastava & Pitblado 1993,
    Journal of Applied Meteorology 32(3):567-573, doi:10.1175/1520-0450(1993)032<0567:UOWDTS>2.0.CO;2).
  * `cart_kim2002`: arvore CART/SLD de Kim, Taylor, Gleason & Koehler (2002,
    Plant Disease 86(2):179-185, doi:10.1094/PDIS.2002.86.2.179) com ajuste
    logaritmico FAO-56 Eq. 47 de vento de 10 m para 2 m quando aplicavel.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .rules.common import HourlyRecord, normalize_records

PRIMARY_LWD_METHOD = "rh90_rain"
SECONDARY_LWD_METHODS = ("dpd_hysteresis", "cart_kim2002")
VALID_LWD_METHODS = (PRIMARY_LWD_METHOD,) + SECONDARY_LWD_METHODS


def magnus_dewpoint_c(temp_c: float, rh_pct: float) -> float:
    """Ponto de orvalho pela aproximacao de Magnus-Tetens (Alduchov & Eskridge 1996)."""
    rh = min(max(rh_pct, 1.0), 100.0)
    a, b = 17.625, 243.04
    gamma = math.log(rh / 100.0) + (a * temp_c) / (b + temp_c)
    return (b * gamma) / (a - gamma)


def wind_10m_to_2m_ms(wind_10m_ms: float) -> float:
    """Ajuste logaritmico padrao FAO-56 Eq. 47 de 10 m para 2 m (~0,748)."""
    factor = 4.87 / math.log(67.8 * 10.0 - 5.42)
    return max(wind_10m_ms, 0.0) * factor


def estimate_lwd_flags(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    method: str = PRIMARY_LWD_METHOD,
    wind_height_m: float = 2.0,
) -> list[bool | None]:
    """
    Retorna lista booleana de molhamento horario estimado sem nunca ler `rec.wet`.
    Horas sem temperatura ou umidade relativa validas (e sem chuva positiva)
    recebem `None`.
    """
    if method not in VALID_LWD_METHODS:
        raise ValueError(f"metodo LWD invalido: {method!r}. Use {VALID_LWD_METHODS}.")
    norm = normalize_records(records)
    out: list[bool | None] = []

    if method == "rh90_rain":
        for rec in norm:
            if rec.precip_mm is not None and rec.precip_mm > 0.0:
                out.append(True)
            elif rec.rh_pct is None:
                out.append(None)
            else:
                out.append(rec.rh_pct >= 90.0)
        return out

    if method == "dpd_hysteresis":
        # Gillespie, Srivastava & Pitblado (1993): DPD <= 1.8 C inicia, DPD >= 3.8 C seca
        state = False
        for rec in norm:
            if rec.precip_mm is not None and rec.precip_mm > 0.0:
                state = True
                out.append(True)
                continue
            if rec.temp_c is None or rec.rh_pct is None:
                state = False
                out.append(None)
                continue
            td = magnus_dewpoint_c(rec.temp_c, rec.rh_pct)
            dpd = rec.temp_c - td
            if state:
                if dpd >= 3.8:
                    state = False
            else:
                if dpd <= 1.8:
                    state = True
            out.append(state)
        return out

    # method == "cart_kim2002": Kim et al. (2002), Plant Disease 86(2):179-185
    for rec in norm:
        if rec.precip_mm is not None and rec.precip_mm > 0.0:
            out.append(True)
            continue
        if rec.temp_c is None or rec.rh_pct is None:
            out.append(None)
            continue
        ti = rec.temp_c
        rhi = rec.rh_pct
        dpdi = ti - magnus_dewpoint_c(ti, rhi)
        w_raw = 1.5 if rec.wind_ms is None else max(rec.wind_ms, 0.0)
        ui = wind_10m_to_2m_ms(w_raw) if wind_height_m >= 5.0 else w_raw

        if dpdi >= 3.7:
            out.append(False)
        elif ui < 2.5:
            t_pos = max(ti, 0.0)
            score = (
                1.6064 * math.sqrt(t_pos)
                + 0.0036 * (ti ** 2)
                + 0.1531 * rhi
                - 0.4599 * ui * dpdi
                - 0.0035 * ti * rhi
            )
            out.append(score > 14.4674)
        elif rhi >= 87.8:
            t_pos = max(ti, 0.0)
            score = (
                0.7921 * math.sqrt(t_pos)
                + 0.0046 * (rhi ** 2)
                - 2.3889 * ui
                - 0.0390 * ti * ui
                + 1.0613 * ui * dpdi
            )
            out.append(score > 37.00)
        else:
            out.append(False)
    return out


def apply_lwd_estimator(
    records: Sequence[HourlyRecord | Mapping[str, Any]],
    method: str = PRIMARY_LWD_METHOD,
    wind_height_m: float = 2.0,
) -> list[HourlyRecord]:
    """
    Substitui o campo `wet` de cada registro pelo molhamento estimado por `method`,
    descartando completamente qualquer leitura previa de sensor fisico.
    """
    norm = normalize_records(records)
    flags = estimate_lwd_flags(norm, method=method, wind_height_m=wind_height_m)
    return [
        HourlyRecord(
            ts=rec.ts,
            temp_c=rec.temp_c,
            rh_pct=rec.rh_pct,
            precip_mm=rec.precip_mm,
            wet=w,
            wind_ms=rec.wind_ms,
            rad_wm2=rec.rad_wm2,
        )
        for rec, w in zip(norm, flags)
    ]
