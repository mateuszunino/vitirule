#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
economics.py
============
Função de dano econômico ao cacho e análise de resultado líquido (€/ha) para
míldio da videira (*Plasmopara viticola*).

Converte AACPD foliar e número de pulverizações em custo total (perda de
produção + custo de aplicação) e margem líquida (€/ha), permitindo avaliar o
trade-off econômico entre pontos da fronteira de Pareto (ex.: economizar
pulverizações em anos secos vs. risco de dano ao cacho em vinhedos de alto
valor agregado).

Parâmetros padrão de referência (viticultura europeia — ajustáveis):
* `gross_revenue_eur_ha` : receita bruta sem doença (ex.: 5.000 €/ha vinho de
  mesa, 12.000 €/ha AOC regional, 25.000 €/ha AOC premium).
* `spray_cost_eur_ha`    : custo completo por aplicação (produto + trator +
  mão de obra; referência 55 €/ha).
* Curva de dano ao cacho (Madden et al. 2007, forma exponencial saturante):
      yield_loss_frac = max_yield_loss * (1 - exp(-damage_slope * aacpd))
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class VineyardEconomicsConfig:
    label: str = "aoc_regional"
    gross_revenue_eur_ha: float = 12_000.0
    spray_cost_eur_ha: float = 55.0
    max_yield_loss_frac: float = 0.85
    damage_slope_per_aacpd: float = 0.00050   # ~4,1 % perda a AACPD=100; ~11,8 % a 300; ~33,4 % a 1000


DEFAULT_SCENARIOS: tuple[VineyardEconomicsConfig, ...] = (
    VineyardEconomicsConfig(label="mesa_5k_eur", gross_revenue_eur_ha=5_000.0, spray_cost_eur_ha=55.0, damage_slope_per_aacpd=0.00050),
    VineyardEconomicsConfig(label="aoc_12k_eur", gross_revenue_eur_ha=12_000.0, spray_cost_eur_ha=55.0, damage_slope_per_aacpd=0.00050),
    VineyardEconomicsConfig(label="premium_25k_eur", gross_revenue_eur_ha=25_000.0, spray_cost_eur_ha=55.0, damage_slope_per_aacpd=0.00050),
)


def bunch_yield_loss_fraction(aacpd: float, cfg: VineyardEconomicsConfig) -> float:
    """Fração esperada de perda de colheita (0 a `max_yield_loss_frac`) a partir da AACPD."""
    a = max(float(aacpd), 0.0)
    return float(cfg.max_yield_loss_frac * (1.0 - math.exp(-cfg.damage_slope_per_aacpd * a)))


def economic_outcome(aacpd: float, n_sprays: float, cfg: VineyardEconomicsConfig) -> dict[str, float]:
    """Calcula perda no cacho (€/ha), custo de pulverização (€/ha), custo total e resultado líquido."""
    loss_frac = bunch_yield_loss_fraction(aacpd, cfg)
    crop_loss_eur = cfg.gross_revenue_eur_ha * loss_frac
    spray_cost_eur = float(n_sprays) * cfg.spray_cost_eur_ha
    total_cost_eur = crop_loss_eur + spray_cost_eur
    net_return_eur = cfg.gross_revenue_eur_ha - total_cost_eur
    return {
        "yield_loss_pct": round(100.0 * loss_frac, 3),
        "crop_loss_eur_ha": round(crop_loss_eur, 2),
        "spray_cost_eur_ha": round(spray_cost_eur, 2),
        "total_cost_eur_ha": round(total_cost_eur, 2),
        "net_return_eur_ha": round(net_return_eur, 2),
    }


def evaluate_pareto_economics(
    pareto_summary: dict,
    scenarios: Sequence[VineyardEconomicsConfig] = DEFAULT_SCENARIOS,
) -> dict[str, Any]:
    """
    Aplica os cenários econômicos sobre um resumo de fronteira de Pareto
    (calendários fixos + pontos de previsão + testemunha).
    """
    entries: list[dict] = []
    if "testemunha" in pareto_summary:
        entries.append(pareto_summary["testemunha"])
    for key in ("calendars", "forecast_v1", "forecast_v2"):
        entries.extend(pareto_summary.get(key) or [])

    by_scenario: dict[str, list[dict]] = {}
    for sc in scenarios:
        rows = []
        for e in entries:
            eco = economic_outcome(e["aacpd_mean"], e["sprays_mean"], sc)
            rows.append({
                "strategy": e["strategy"],
                "sprays_mean": e["sprays_mean"],
                "aacpd_mean": e["aacpd_mean"],
                **eco,
            })
        # Ordena por melhor resultado líquido (€/ha decrescente)
        best_net = max(r["net_return_eur_ha"] for r in rows)
        for r in rows:
            r["delta_vs_best_eur_ha"] = round(r["net_return_eur_ha"] - best_net, 2)
        by_scenario[sc.label] = sorted(rows, key=lambda r: r["net_return_eur_ha"], reverse=True)
    return by_scenario


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliação econômica (€/ha) da fronteira de Pareto.")
    parser.add_argument("pareto_json", help="JSON gerado por pareto_analysis.py")
    parser.add_argument("--out-json", help="grava resultado econômico neste arquivo")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.pareto_json).read_text(encoding="utf-8"))
    report = {
        "source_pareto": str(args.pareto_json),
        "pooled_economics": evaluate_pareto_economics(data["pooled"]),
    }
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
