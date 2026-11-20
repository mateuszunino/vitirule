#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
economics.py
============
Função de dano econômico ao cacho, mapa de sensibilidade (inclinação do dano ×
receita bruta) e análise do teto europeu de cobre para viticultura orgânica
(Regulamento de Execução (UE) 2018/1981: 28 kg Cu/ha em 7 anos = média de
4,0 kg Cu/ha/ano).

Curva de dano (forma exponencial saturante, Madden et al. 2007):
    yield_loss_frac = max_yield_loss * (1 - exp(-damage_slope * aacpd))

Como `damage_slope` não é calibrado em campo neste projeto, o resultado é
sempre acompanhado da superfície de sensibilidade de `0,0002` a `0,0015` por
unidade de AACPD e de `3.000` a `30.000 €/ha` de receita bruta.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

# Regulamento de Execução (UE) 2018/1981: 28 kg Cu/ha em 7 anos (média 4,0 kg/ha/ano)
EU_COPPER_LIMIT_7Y_KG_HA: float = 28.0
EU_COPPER_LIMIT_ANNUAL_AVG_KG_HA: float = EU_COPPER_LIMIT_7Y_KG_HA / 7.0
DEFAULT_COPPER_DOSE_KG_HA: float = 0.50   # dose típica efetiva em viticultura orgânica (0,4–0,6 kg Cu/ha)


@dataclass(frozen=True)
class VineyardEconomicsConfig:
    label: str = "aoc_regional"
    gross_revenue_eur_ha: float = 12_000.0
    spray_cost_eur_ha: float = 55.0
    max_yield_loss_frac: float = 0.85
    damage_slope_per_aacpd: float = 0.00050


DEFAULT_SCENARIOS: tuple[VineyardEconomicsConfig, ...] = (
    VineyardEconomicsConfig(label="mesa_5k_eur", gross_revenue_eur_ha=5_000.0, spray_cost_eur_ha=55.0),
    VineyardEconomicsConfig(label="aoc_12k_eur", gross_revenue_eur_ha=12_000.0, spray_cost_eur_ha=55.0),
    VineyardEconomicsConfig(label="premium_25k_eur", gross_revenue_eur_ha=25_000.0, spray_cost_eur_ha=55.0),
)


def bunch_yield_loss_fraction(aacpd: float, cfg: VineyardEconomicsConfig) -> float:
    a = max(float(aacpd), 0.0)
    return float(cfg.max_yield_loss_frac * (1.0 - math.exp(-cfg.damage_slope_per_aacpd * a)))


def economic_outcome(
    aacpd: float,
    n_sprays: float,
    cfg: VineyardEconomicsConfig,
    copper_dose_kg_ha: float = DEFAULT_COPPER_DOSE_KG_HA,
) -> dict[str, Any]:
    loss_frac = bunch_yield_loss_fraction(aacpd, cfg)
    crop_loss_eur = cfg.gross_revenue_eur_ha * loss_frac
    spray_cost_eur = float(n_sprays) * cfg.spray_cost_eur_ha
    total_cost_eur = crop_loss_eur + spray_cost_eur
    net_return_eur = cfg.gross_revenue_eur_ha - total_cost_eur
    copper_annual_kg = float(n_sprays) * copper_dose_kg_ha
    copper_7y_kg = copper_annual_kg * 7.0
    return {
        "yield_loss_pct": round(100.0 * loss_frac, 3),
        "crop_loss_eur_ha": round(crop_loss_eur, 2),
        "spray_cost_eur_ha": round(spray_cost_eur, 2),
        "total_cost_eur_ha": round(total_cost_eur, 2),
        "net_return_eur_ha": round(net_return_eur, 2),
        "copper_annual_kg_ha": round(copper_annual_kg, 3),
        "copper_7y_projected_kg_ha": round(copper_7y_kg, 2),
        "complies_eu_2018_1981": bool(copper_7y_kg <= EU_COPPER_LIMIT_7Y_KG_HA),
    }


def _extract_entries(pareto_summary: dict) -> list[dict]:
    entries: list[dict] = []
    if "testemunha" in pareto_summary:
        entries.append(pareto_summary["testemunha"])
    for key in ("calendars", "forecast_v1", "forecast_v2", "rules"):
        entries.extend(pareto_summary.get(key) or [])
    return entries


def evaluate_pareto_economics(
    pareto_summary: dict,
    scenarios: Sequence[VineyardEconomicsConfig] = DEFAULT_SCENARIOS,
    copper_dose_kg_ha: float = DEFAULT_COPPER_DOSE_KG_HA,
) -> dict[str, Any]:
    entries = _extract_entries(pareto_summary)
    by_scenario: dict[str, list[dict]] = {}
    for sc in scenarios:
        rows = []
        for e in entries:
            eco = economic_outcome(e["aacpd_mean"], e["sprays_mean"], sc, copper_dose_kg_ha=copper_dose_kg_ha)
            rows.append({
                "strategy": e["strategy"],
                "sprays_mean": e["sprays_mean"],
                "aacpd_mean": e["aacpd_mean"],
                **eco,
            })
        best_net = max(r["net_return_eur_ha"] for r in rows)
        compliant_rows = [r for r in rows if r["complies_eu_2018_1981"]]
        best_copper_net = max(r["net_return_eur_ha"] for r in compliant_rows) if compliant_rows else None
        for r in rows:
            r["delta_vs_best_eur_ha"] = round(r["net_return_eur_ha"] - best_net, 2)
            r["delta_vs_best_eu_copper_eur_ha"] = (
                round(r["net_return_eur_ha"] - best_copper_net, 2)
                if (best_copper_net is not None and r["complies_eu_2018_1981"])
                else None
            )
        by_scenario[sc.label] = sorted(rows, key=lambda r: r["net_return_eur_ha"], reverse=True)
    return by_scenario


def sensitivity_grid(
    pareto_summary: dict,
    slopes: Sequence[float] = tuple(np.round(np.linspace(0.0002, 0.0015, 14), 5)),
    revenues: Sequence[float] = (3000, 5000, 7500, 10000, 12000, 15000, 20000, 25000, 30000),
    spray_cost_eur_ha: float = 55.0,
    enforce_eu_copper: bool = False,
    copper_dose_kg_ha: float = DEFAULT_COPPER_DOSE_KG_HA,
) -> dict[str, Any]:
    """
    Varre a grade (`damage_slope` × `gross_revenue_eur_ha`) e retorna qual
    estratégia maximiza o retorno líquido em cada célula (com ou sem restrição
    do teto europeu de cobre 2018/1981).
    """
    entries = _extract_entries(pareto_summary)
    if enforce_eu_copper:
        entries = [
            e for e in entries
            if (float(e["sprays_mean"]) * copper_dose_kg_ha * 7.0) <= EU_COPPER_LIMIT_7Y_KG_HA
        ]

    grid: list[list[str]] = []
    win_counts: dict[str, int] = {}
    for rev in revenues:
        row_winners: list[str] = []
        for sl in slopes:
            cfg = VineyardEconomicsConfig(
                gross_revenue_eur_ha=float(rev),
                spray_cost_eur_ha=spray_cost_eur_ha,
                damage_slope_per_aacpd=float(sl),
            )
            best_e = max(
                entries,
                key=lambda e: economic_outcome(e["aacpd_mean"], e["sprays_mean"], cfg)["net_return_eur_ha"],
            )
            w = best_e["strategy"]
            row_winners.append(w)
            win_counts[w] = win_counts.get(w, 0) + 1
        grid.append(row_winners)

    total_cells = len(revenues) * len(slopes)
    win_share = {k: round(100.0 * v / total_cells, 1) for k, v in sorted(win_counts.items(), key=lambda kv: -kv[1])}
    return {
        "enforce_eu_copper_2018_1981": enforce_eu_copper,
        "copper_dose_kg_ha": copper_dose_kg_ha,
        "spray_cost_eur_ha": spray_cost_eur_ha,
        "slopes": [float(s) for s in slopes],
        "revenues_eur_ha": [float(r) for r in revenues],
        "winner_share_pct": win_share,
        "grid_revenues_by_slopes": grid,
    }


def write_sensitivity_svg(sens: dict, title: str, out_path: str | Path) -> Path:
    """Gera mapa de decisão SVG: eixo X = inclinação do dano, eixo Y = receita (€/ha), cor = estratégia vencedora."""
    slopes = sens["slopes"]
    revs = sens["revenues_eur_ha"]
    grid = sens["grid_revenues_by_slopes"]

    palette = {
        "cal_7d": "#1f2937",
        "cal_10d": "#6b7280",
        "cal_12d": "#9ca3af",
        "cal_14d": "#d1d5db",
        "fc_v1_T10": "#059669",
        "om_v1_T10": "#059669",
        "st_v1_T10": "#0284c7",
        "fc_v2_T10": "#d97706",
        "om_v2_T10": "#d97706",
        "st_v2_T10": "#7c3aed",
        "testemunha": "#dc2626",
    }

    W, H = 760, 440
    ml, mr, mt, mb = 86, 170, 46, 56
    pw, ph = W - ml - mr, H - mt - mb
    cw = pw / len(slopes)
    ch = ph / len(revs)

    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" style="font-family:Segoe UI,Arial,sans-serif;background:#fff">',
        f'<text x="{(ml+pw/2):.1f}" y="26" text-anchor="middle" font-size="14" font-weight="600" fill="#111827">{title}</text>',
        f'<text x="{(ml+pw/2):.1f}" y="{H-14}" text-anchor="middle" font-size="11.5" fill="#374151">Inclinação da curva de dano (k por unidade de AACPD)</text>',
        f'<text x="18" y="{(mt+ph/2):.1f}" text-anchor="middle" font-size="11.5" fill="#374151" transform="rotate(-90 18 {(mt+ph/2):.1f})">Receita bruta sem doença (€/ha)</text>',
    ]

    for r_idx, rev in enumerate(revs):
        # Maior receita no topo
        y = mt + (len(revs) - 1 - r_idx) * ch
        elems.append(f'<text x="{ml-8}" y="{y + ch/2 + 4:.1f}" text-anchor="end" font-size="10" fill="#374151">{int(rev):,}</text>')
        for c_idx, sl in enumerate(slopes):
            x = ml + c_idx * cw
            w = grid[r_idx][c_idx]
            col = palette.get(w, "#4b5563")
            elems.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw:.1f}" height="{ch:.1f}" fill="{col}" stroke="#fff" stroke-width="1"/>')

    for c_idx, sl in enumerate(slopes):
        if c_idx % 2 == 0:
            x = ml + (c_idx + 0.5) * cw
            elems.append(f'<text x="{x:.1f}" y="{mt+ph+16:.1f}" text-anchor="middle" font-size="9.5" fill="#374151">{sl:.4f}</text>')

    # Legenda
    lx, ly = ml + pw + 14, mt + 12
    elems.append(f'<text x="{lx}" y="{ly}" font-size="11" font-weight="600" fill="#111827">Estratégia vencedora</text>')
    for idx, (strat, pct) in enumerate(sens["winner_share_pct"].items()):
        yy = ly + 20 + idx * 20
        col = palette.get(strat, "#4b5563")
        elems.append(f'<rect x="{lx}" y="{yy-10}" width="12" height="12" fill="{col}"/>')
        elems.append(f'<text x="{lx+18}" y="{yy}" font-size="10.5" fill="#1f2937">{strat} ({pct:.0f}%)</text>')

    elems.append("</svg>")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(elems), encoding="utf-8")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliação econômica (€/ha), sensibilidade e teto de cobre UE 2018/1981.")
    parser.add_argument("pareto_json", help="JSON gerado por pareto_analysis.py ou semireal_osse.py")
    parser.add_argument("--out-json", help="grava resultado econômico completo neste arquivo")
    parser.add_argument("--out-svg-unconstrained", help="mapa SVG de sensibilidade sem restrição de cobre")
    parser.add_argument("--out-svg-copper", help="mapa SVG de sensibilidade sob Reg. (UE) 2018/1981 (28 kg/7a)")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.pareto_json).read_text(encoding="utf-8"))
    pooled = raw["inrae_semireal_sensor_truth"]["pooled"] if "inrae_semireal_sensor_truth" in raw else raw["pooled"]

    sens_free = sensitivity_grid(pooled, enforce_eu_copper=False)
    sens_cu = sensitivity_grid(pooled, enforce_eu_copper=True)

    if args.out_svg_unconstrained:
        write_sensitivity_svg(sens_free, "Estratégia vencedora (€/ha) — Sem teto de cobre", args.out_svg_unconstrained)
    if args.out_svg_copper:
        write_sensitivity_svg(sens_cu, "Estratégia vencedora (€/ha) — Sob Reg. UE 2018/1981 (<= 4 kg Cu/ha/ano)", args.out_svg_copper)

    report = {
        "source": str(args.pareto_json),
        "eu_copper_regulation": "Commission Implementing Regulation (EU) 2018/1981 (28 kg Cu/ha / 7 years)",
        "pooled_economics": evaluate_pareto_economics(pooled),
        "sensitivity_unconstrained": sens_free,
        "sensitivity_eu_copper_2018_1981": sens_cu,
    }
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sensitivity_unconstrained_share": sens_free["winner_share_pct"],
        "sensitivity_eu_copper_share": sens_cu["winner_share_pct"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
