"""
vitirule_v2.metrics
===================
Metricas pre-registradas de avaliacao de alertas da Fase 3 (Secao 7 de
`docs/v2/preregistro.md`). Biblioteca padrao Python pura (compativel com Pyodide).

Inclui:
- Pareamento temporal um-para-um com tolerancias fixas por regra
- Taxa de alertas perdidos, razao de alarmes falsos (FAR), F1 e atraso com sinal
  (positivo quando a fonte alerta depois da referencia)
- Concordancia de severidade para Mills revisada
- Avaliacao por intervalo sincronizado (`reference_reset`) para TOM-CAST
- Modelo de custo-perda diario (Richardson 2000; Kim, Beresford & Henshall 2008)
  com tabela de contingencia completa incluindo acertos negativos
- Bootstrap em bloco por estacao (2.000 reamostragens; omitido quando n < 3)
- Criterio binario pre-registrado de usabilidade da fonte
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc

MATCH_TOLERANCES_HOURS: dict[str, float] = {
    "rule_3_10": 48.0,        # +/- 2 dias
    "goidanich": 48.0,        # +/- 2 dias
    "mills_revised": 24.0,    # +/- 24 horas em light_ts
    "tomcast_self": 72.0,     # +/- 3 dias
}

COST_LOSS_RATIOS: tuple[float, ...] = (0.05, 0.10, 0.20)

USABILITY_CRITERIA: dict[str, float] = {
    "max_missed_rate": 0.20,
    "max_far": 0.30,
    "max_median_lag_days": 1.0,
    "max_missed_rate_ci95_hi_exclusive": 0.30,
}


def _to_utc_dt(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"datetime sem fuso horario: {value!r}")
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 0, 0, tzinfo=UTC)
    raise TypeError(f"tipo temporal invalido: {type(value).__name__}")


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Percentil linear em `[0, 1]` sobre lista ja ordenada e nao vazia."""
    if not sorted_vals:
        raise ValueError("lista vazia para percentil")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]))


def _summarize_lags(lags_days: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if not lags_days:
        return None, None, None
    s = sorted(float(v) for v in lags_days)
    return (
        round(_percentile(s, 0.50), 4),
        round(_percentile(s, 0.25), 4),
        round(_percentile(s, 0.75), 4),
    )


@dataclass(frozen=True)
class EventMatchResult:
    tp: int
    fp: int
    fn: int
    n_ref: int
    n_cand: int
    missed_rate: float | None
    far: float | None
    f1: float | None
    median_lag_days: float | None
    iqr_lag_days: tuple[float, float] | None
    matched_pairs: tuple[tuple[int, int, float], ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["iqr_lag_days"] = list(self.iqr_lag_days) if self.iqr_lag_days is not None else None
        d["matched_pairs"] = [list(p) for p in self.matched_pairs]
        return d


def match_events_one_to_one(
    ref_times: Sequence[date | datetime],
    cand_times: Sequence[date | datetime],
    tolerance_hours: float,
) -> EventMatchResult:
    """
    Pareamento guloso um-para-um ordenado pela menor distancia temporal absoluta
    dentro de `tolerance_hours`.

    Atraso com sinal (`signed_lag_days = (t_cand - t_ref) / 86400`):
    - positivo quando a fonte candidata alerta DEPOIS da referencia (atraso)
    - negativo quando a fonte candidata alerta ANTES da referencia (antecipacao)
    """
    if tolerance_hours < 0:
        raise ValueError("tolerance_hours deve ser nao negativo")

    r_dts = [_to_utc_dt(t) for t in ref_times]
    c_dts = [_to_utc_dt(t) for t in cand_times]

    candidates: list[tuple[float, float, int, int]] = []
    for ri, r_dt in enumerate(r_dts):
        for ci, c_dt in enumerate(c_dts):
            diff_h = (c_dt - r_dt).total_seconds() / 3600.0
            abs_h = abs(diff_h)
            if abs_h <= tolerance_hours + 1e-9:
                candidates.append((abs_h, diff_h, ri, ci))

    candidates.sort(key=lambda x: (x[0], x[2], x[3]))

    used_ref: set[int] = set()
    used_cand: set[int] = set()
    pairs: list[tuple[int, int, float]] = []

    for _abs_h, diff_h, ri, ci in candidates:
        if ri in used_ref or ci in used_cand:
            continue
        used_ref.add(ri)
        used_cand.add(ci)
        pairs.append((ri, ci, round(diff_h / 24.0, 4)))

    pairs.sort(key=lambda x: x[0])

    tp = len(pairs)
    fn = len(r_dts) - tp
    fp = len(c_dts) - tp
    n_ref = len(r_dts)
    n_cand = len(c_dts)

    missed_rate = round(fn / n_ref, 4) if n_ref > 0 else None
    far = round(fp / n_cand, 4) if n_cand > 0 else None
    denom_f1 = 2 * tp + fp + fn
    f1 = round((2 * tp) / denom_f1, 4) if denom_f1 > 0 else None

    med, p25, p75 = _summarize_lags([p[2] for p in pairs])
    iqr = (p25, p75) if (p25 is not None and p75 is not None) else None

    return EventMatchResult(
        tp=tp,
        fp=fp,
        fn=fn,
        n_ref=n_ref,
        n_cand=n_cand,
        missed_rate=missed_rate,
        far=far,
        f1=f1,
        median_lag_days=med,
        iqr_lag_days=iqr,
        matched_pairs=tuple(pairs),
    )


def mills_severity_concordance(
    ref_severities: Sequence[str],
    cand_severities: Sequence[str],
    matched_pairs: Sequence[tuple[int, int, float]],
) -> dict[str, Any]:
    """Avalia concordancia exata e subestimacao de severidade entre pares Mills."""
    rank = {"light": 1, "moderate": 2, "heavy": 3}
    n = len(matched_pairs)
    if n == 0:
        return {"n_matched": 0, "exact_match_rate": None, "underclassified_rate": None, "overclassified_rate": None}
    exact = under = over = 0
    for ri, ci, _lag in matched_pairs:
        rr = rank[ref_severities[ri]]
        cr = rank[cand_severities[ci]]
        if cr == rr:
            exact += 1
        elif cr < rr:
            under += 1
        else:
            over += 1
    return {
        "n_matched": n,
        "exact_match_rate": round(exact / n, 4),
        "underclassified_rate": round(under / n, 4),
        "overclassified_rate": round(over / n, 4),
    }


def compute_daily_cost_loss(
    unmasked_days: Iterable[date],
    ref_alert_days: Iterable[date],
    cand_alert_days: Iterable[date],
    cost_loss_ratios: Sequence[float] = COST_LOSS_RATIOS,
) -> dict[str, Any]:
    """
    Modelo de custo-perda diario (Richardson 2000; Kim, Beresford & Henshall 2008).

    Unidade de decisao: cada dia nao mascarado dentro da janela fenologica.
    Tabela de contingencia:
    - `a` (hits): referencia = 1, candidata = 1 -> custo C
    - `b` (false alarms): referencia = 0, candidata = 1 -> custo C
    - `c` (misses): referencia = 1, candidata = 0 -> custo L
    - `d` (correct negatives): referencia = 0, candidata = 0 -> custo 0

    Valor relativo:
        V(r) = (E_best_fixed - E_cand) / (E_best_fixed - E_perfect)
    onde `r = C / L`, `E_best_fixed = min(r, s)`, `E_perfect = s * r` e `s = (a + c) / N`.
    """
    valid_set = set(unmasked_days)
    ref_set = set(ref_alert_days) & valid_set
    cand_set = set(cand_alert_days) & valid_set

    a = len(ref_set & cand_set)
    b = len(cand_set - ref_set)
    c = len(ref_set - cand_set)
    d_tn = len(valid_set - ref_set - cand_set)

    return cost_loss_from_counts(a, b, c, d_tn, cost_loss_ratios=cost_loss_ratios)


def cost_loss_from_counts(
    a: int,
    b: int,
    c: int,
    d_tn: int,
    cost_loss_ratios: Sequence[float] = COST_LOSS_RATIOS,
) -> dict[str, Any]:
    """Calcula valor relativo de custo-perda diretamente a partir de `(a, b, c, d)`."""
    n = a + b + c + d_tn
    if n == 0:
        return {
            "n_days": 0,
            "contingency": {"a_hit": 0, "b_false_alarm": 0, "c_miss": 0, "d_correct_neg": 0},
            "base_rate": None,
            "by_ratio": {},
        }
    s = (a + c) / n
    by_ratio: dict[str, dict[str, float | None]] = {}
    for r in cost_loss_ratios:
        e_cand = ((a + b) * r + c) / n
        e_never = s
        e_always = r
        e_best_fixed = min(e_always, e_never)
        e_perfect = s * r
        denom = e_best_fixed - e_perfect
        val = ((e_best_fixed - e_cand) / denom) if denom > 1e-12 else None
        by_ratio[f"{r:.2f}"] = {
            "cost_loss_ratio": r,
            "expense_cand": round(e_cand, 5),
            "expense_never": round(e_never, 5),
            "expense_always": round(e_always, 5),
            "expense_best_fixed": round(e_best_fixed, 5),
            "expense_perfect": round(e_perfect, 5),
            "relative_value": round(val, 4) if val is not None else None,
        }
    return {
        "n_days": n,
        "contingency": {"a_hit": a, "b_false_alarm": b, "c_miss": c, "d_correct_neg": d_tn},
        "base_rate": round(s, 5),
        "by_ratio": by_ratio,
    }


def evaluate_usability(
    missed_rate: float | None,
    far: float | None,
    median_lag_days: float | None,
    missed_rate_ci95_hi: float | None,
) -> dict[str, Any]:
    """
    Aplica o criterio pre-registrado de usabilidade:
    - alertas perdidos <= 20%
    - razao de alarmes falsos (FAR) <= 30%
    - atraso mediano <= 1,0 dia
    - limite superior do IC 95% de alertas perdidos < 30%
    """
    c_missed = (missed_rate is not None) and (missed_rate <= USABILITY_CRITERIA["max_missed_rate"])
    c_far = (far is not None) and (far <= USABILITY_CRITERIA["max_far"])
    c_lag = (median_lag_days is not None) and (median_lag_days <= USABILITY_CRITERIA["max_median_lag_days"])
    c_ci = (
        (missed_rate_ci95_hi is not None)
        and (missed_rate_ci95_hi < USABILITY_CRITERIA["max_missed_rate_ci95_hi_exclusive"])
    )
    return {
        "usable": bool(c_missed and c_far and c_lag and c_ci),
        "checks": {
            "missed_rate_le_020": c_missed,
            "far_le_030": c_far,
            "median_lag_le_1d": c_lag,
            "missed_ci95_hi_lt_030": c_ci,
        },
    }


def aggregate_station_metrics_with_bootstrap(
    station_blocks: Sequence[Mapping[str, Any]],
    cost_loss_ratios: Sequence[float] = COST_LOSS_RATIOS,
    n_boot: int = 2000,
    seed: int = 20261122,
    compute_ci: bool = True,
) -> dict[str, Any]:
    """
    Agrega metricas de eventos e custo-perda a partir de blocos por estacao
    (cada bloco agrega todas as safras de uma mesma estacao) e calcula ICs de
    95% por bootstrap em bloco por estacao.

    Quando `compute_ci=False` ou `len(station_blocks) < 3` (ex.: Politecnico
    com 2 estacoes), retorna apenas estimativas pontuais descritivas sem IC.
    """
    blocks = list(station_blocks)
    n_st = len(blocks)

    def _compute_point(subset: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        tp = sum(int(b["tp"]) for b in subset)
        fp = sum(int(b["fp"]) for b in subset)
        fn = sum(int(b["fn"]) for b in subset)
        lags = [float(v) for b in subset for v in b.get("lags_days", ())]
        a = sum(int(b.get("a_hit", 0)) for b in subset)
        bf = sum(int(b.get("b_false_alarm", 0)) for b in subset)
        c = sum(int(b.get("c_miss", 0)) for b in subset)
        d_tn = sum(int(b.get("d_correct_neg", 0)) for b in subset)

        n_ref = tp + fn
        n_cand = tp + fp
        missed = (fn / n_ref) if n_ref > 0 else None
        far = (fp / n_cand) if n_cand > 0 else None
        f1 = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else None
        med, p25, p75 = _summarize_lags(lags)
        cl = cost_loss_from_counts(a, bf, c, d_tn, cost_loss_ratios=cost_loss_ratios)
        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "n_ref": n_ref,
            "n_cand": n_cand,
            "missed_rate": round(missed, 4) if missed is not None else None,
            "far": round(far, 4) if far is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
            "median_lag_days": med,
            "iqr_lag_days": [p25, p75] if (p25 is not None and p75 is not None) else None,
            "cost_loss": cl,
        }

    point = _compute_point(blocks)
    cis: dict[str, list[float] | None] | None = None

    if compute_ci and n_st >= 3:
        rng = random.Random(seed)
        boot_missed: list[float] = []
        boot_far: list[float] = []
        boot_f1: list[float] = []
        boot_lag: list[float] = []
        boot_cl: dict[str, list[float]] = {f"{r:.2f}": [] for r in cost_loss_ratios}

        for _ in range(n_boot):
            sample = [blocks[rng.randrange(n_st)] for _ in range(n_st)]
            pt = _compute_point(sample)
            if pt["missed_rate"] is not None:
                boot_missed.append(pt["missed_rate"])
            if pt["far"] is not None:
                boot_far.append(pt["far"])
            if pt["f1"] is not None:
                boot_f1.append(pt["f1"])
            if pt["median_lag_days"] is not None:
                boot_lag.append(pt["median_lag_days"])
            for r_key, info in pt["cost_loss"]["by_ratio"].items():
                if info["relative_value"] is not None:
                    boot_cl[r_key].append(info["relative_value"])

        def _ci(vals: list[float]) -> list[float] | None:
            if not vals:
                return None
            s = sorted(vals)
            return [round(_percentile(s, 0.025), 4), round(_percentile(s, 0.975), 4)]

        cis = {
            "missed_rate": _ci(boot_missed),
            "far": _ci(boot_far),
            "f1": _ci(boot_f1),
            "median_lag_days": _ci(boot_lag),
            **{f"cost_loss_v_{k}": _ci(v) for k, v in boot_cl.items()},
        }

    missed_ci_hi = (
        cis["missed_rate"][1]
        if (cis is not None and cis.get("missed_rate") is not None)
        else None
    )
    usability = evaluate_usability(
        point["missed_rate"], point["far"], point["median_lag_days"], missed_ci_hi
    )

    return {
        "n_stations": n_st,
        "point": point,
        "ci95_station_bootstrap": cis,
        "usability_check": usability,
    }
