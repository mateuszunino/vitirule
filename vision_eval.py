#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision_eval.py
==============
Avaliação objetiva do pipeline de visão computacional contra os critérios da
seção 7 do BRIEFING.md e seção 8 do SKILL.md:

* Coeficiente de concordância de Lin (CCC) >= 0,90 entre a severidade medida
  pelo pipeline e a anotada manualmente em imagens/vídeos de validação.
* Erro relativo de área foliar calibrada < 5 % em vídeos com quadrado de
  referência de 2 x 2 cm.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

LIN_CCC_TARGET: float = 0.90
AREA_ERROR_PCT_TARGET: float = 5.0


def lin_ccc(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, float]:
    """
    Calcula o coeficiente de concordância de Lin (1989):
        CCC = 2 * cov(x, y) / (var(x) + var(y) + (mean(x) - mean(y))^2)
    Retorna também correlação de Pearson `r`, fator de correção de viés `cb`,
    MAE, RMSE e viés médio (Bland-Altman).
    """
    x = np.asarray(y_true, dtype=float)
    y = np.asarray(y_pred, dtype=float)
    if x.shape != y.shape or x.size < 2:
        raise ValueError("y_true e y_pred devem ter o mesmo tamanho (>= 2)")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("valores não finitos em y_true ou y_pred")

    mx, my = float(np.mean(x)), float(np.mean(y))
    vx = float(np.var(x, ddof=0))
    vy = float(np.var(y, ddof=0))
    cov = float(np.mean((x - mx) * (y - my)))

    denom = vx + vy + (mx - my) ** 2
    ccc = 1.0 if denom == 0.0 else (2.0 * cov) / denom
    pearson = 1.0 if (vx == 0.0 and vy == 0.0) else (0.0 if (vx == 0.0 or vy == 0.0) else cov / math.sqrt(vx * vy))
    cb = (ccc / pearson) if abs(pearson) > 1e-12 else 0.0

    diff = y - x
    bias = float(np.mean(diff))
    sd_diff = float(np.std(diff, ddof=1))
    return {
        "n": int(x.size),
        "lin_ccc": round(float(ccc), 5),
        "pearson_r": round(float(pearson), 5),
        "bias_correction_cb": round(float(cb), 5),
        "mae_pct": round(float(np.mean(np.abs(diff))), 4),
        "rmse_pct": round(float(np.sqrt(np.mean(diff ** 2))), 4),
        "bland_altman_bias_pct": round(bias, 4),
        "bland_altman_loa95": [round(bias - 1.96 * sd_diff, 4), round(bias + 1.96 * sd_diff, 4)],
        "meets_target": bool(ccc >= LIN_CCC_TARGET),
    }


def area_calibration_error(area_true_cm2: Sequence[float], area_pred_cm2: Sequence[float]) -> dict[str, float]:
    """Calcula erro relativo percentual de calibração de área foliar (meta < 5 %)."""
    t = np.asarray(area_true_cm2, dtype=float)
    p = np.asarray(area_pred_cm2, dtype=float)
    if t.shape != p.shape or t.size == 0:
        raise ValueError("vetores de área inválidos")
    if np.any(t <= 0):
        raise ValueError("area_true_cm2 deve ser estritamente positiva")
    rel_err = np.abs(p - t) / t * 100.0
    mean_err = float(np.mean(rel_err))
    return {
        "n": int(t.size),
        "mean_rel_error_pct": round(mean_err, 4),
        "median_rel_error_pct": round(float(np.median(rel_err)), 4),
        "max_rel_error_pct": round(float(np.max(rel_err)), 4),
        "meets_target": bool(mean_err < AREA_ERROR_PCT_TARGET),
    }


def evaluate_csv(path: str | Path) -> dict:
    """
    Lê CSV de validação com colunas:
      `sample_id, severity_true_pct, severity_pred_pct`
    e opcionalmente `area_true_cm2, area_pred_cm2`.
    """
    y_true, y_pred = [], []
    a_true, a_pred = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            y_true.append(float(row["severity_true_pct"]))
            y_pred.append(float(row["severity_pred_pct"]))
            if row.get("area_true_cm2") and row.get("area_pred_cm2"):
                a_true.append(float(row["area_true_cm2"]))
                a_pred.append(float(row["area_pred_cm2"]))

    report = {"severity": lin_ccc(y_true, y_pred)}
    if a_true:
        report["area_calibration"] = area_calibration_error(a_true, a_pred)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Avalia severidade (CCC de Lin) e calibração de área.")
    parser.add_argument("csv_path", help="CSV com severity_true_pct, severity_pred_pct [, area_true_cm2, area_pred_cm2]")
    args = parser.parse_args(argv)
    report = evaluate_csv(args.csv_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sev_ok = report["severity"]["meets_target"]
    area_ok = report.get("area_calibration", {}).get("meets_target", True)
    return 0 if (sev_ok and area_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
