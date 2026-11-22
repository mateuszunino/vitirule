# -*- coding: utf-8 -*-
"""
Testes das Fases 1 e 2:
* Fase 2 (`climate_retrospective.py`): retrospectiva mensal/sazonal TOM-CAST e Wallin.
* Fase 1 (`vision_prep.py` e `vision_eval.py`): conversão máscara <-> polígono YOLO-seg,
  recorte cinza 114, pré-anotação, divisão sem vazamento de grupos, YAMLs, CCC de Lin
  e erro de calibração de área.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import climate_retrospective as cr
import simulator as sim
import vision_eval as ve
import vision_prep as vp_prep

UTC = timezone.utc


# --------------------------------------------------------------------------
# Fase 2: retrospectiva climática
# --------------------------------------------------------------------------
def test_retrospective_monthly_and_seasonal_aggregation():
    weather = sim.generate_synthetic_weather(
        datetime(2025, 1, 1, 0, tzinfo=UTC),
        days=95, seed=11, mean_temp_c=24.0, mean_rh_pct=84.0, rain_prob=0.10,
    )
    retro = cr.compute_retrospective(weather)
    assert retro["n_days"] >= 94
    assert len(retro["monthly"]) >= 3
    seasons = {r["season"] for r in retro["seasonal"]}
    assert "Verao" in seasons and "Outono" in seasons
    for row in retro["monthly"]:
        assert row["tomcast_dsv_sum"] >= 0
        assert row["wallin_sv_sum"] >= 0


# --------------------------------------------------------------------------
# Fase 1: preparação de datasets e avaliação objetiva de visão
# --------------------------------------------------------------------------
def test_mask_polygon_roundtrip_and_gray_114_crop():
    img = np.full((300, 400, 3), (200, 60, 20), dtype=np.uint8)   # fundo azul-royal
    leaf = np.zeros((300, 400), dtype=np.uint8)
    cv2.ellipse(leaf, (200, 150), (90, 50), 0, 0, 360, 1, -1)
    img[leaf > 0] = (50, 150, 50)

    nec = np.zeros((300, 400), dtype=np.uint8)
    cv2.circle(nec, (190, 150), 14, 1, -1)
    chl = np.zeros((300, 400), dtype=np.uint8)
    cv2.circle(chl, (190, 150), 22, 1, -1)   # sobrepõe necrose -> necrose deve prevalecer

    crop, nec_c, chl_c = vp_prep.build_stage_b_crop(img, leaf, nec, chl, crop_pad=0.04)
    # Cantos fora da folha devem ser exatamente cinza 114 (SKILL.md seção 8)
    assert tuple(int(v) for v in crop[0, 0]) == (114, 114, 114)
    # Necrose e clorose não podem se sobrepor
    assert int(((nec_c > 0) & (chl_c > 0)).sum()) == 0
    assert int(nec_c.sum()) > 100 and int(chl_c.sum()) > 100

    # Roundtrip máscara -> polígono YOLO-seg -> máscara
    lines = vp_prep.mask_to_yolo_polygons(leaf, class_id=0)
    assert len(lines) == 1
    assert lines[0].startswith("0 ")


def test_preannotate_synthetic_leaf_and_group_split_no_leakage(tmp_path):
    # Imagem sintética: fundo EVA azul-royal + folha verde + lesão marrom + quadrado branco
    img = np.full((600, 800, 3), (195, 55, 25), dtype=np.uint8)
    cv2.ellipse(img, (420, 300), (170, 100), 0, 0, 360, (45, 145, 55), -1)
    cv2.circle(img, (410, 290), 22, (35, 55, 115), -1)        # necrose
    cv2.rectangle(img, (70, 70), (190, 190), (240, 240, 240), -1)  # quadrado 2x2 cm

    src_imgs = tmp_path / "raw"
    src_imgs.mkdir()
    for name in (
        "V01-F1_20261201T0900_f0001.jpg",
        "V01-F1_20261201T0900_f0015.jpg",
        "V05-F2_20261201T0905_f0002.jpg",
        "V05-F2_20261201T0905_f0020.jpg",
        "V15-F1_20261201T0910_f0005.jpg",
    ):
        cv2.imwrite(str(src_imgs / name), img)

    pre_dir = tmp_path / "pre"
    for p in sorted(src_imgs.glob("*.jpg")):
        info = vp_prep.preannotate_image(p, pre_dir)
        assert info["leaf_found"] is True
        assert info["stage_b_created"] is True

    split_dir = tmp_path / "split_a"
    split_info = vp_prep.organize_yolo_split(pre_dir / "stage_a", split_dir, stage="stage_a")
    assert set(split_info["train_groups"]).isdisjoint(set(split_info["val_groups"]))
    # V05 e V15 devem cair obrigatoriamente na validação (SKILL.md seção 8)
    assert "V05" in split_info["val_groups"]
    assert "V15" in split_info["val_groups"]
    assert "V01" in split_info["train_groups"]

    yaml_text = (split_dir / "stage_a.yaml").read_text(encoding="utf-8")
    assert "0: leaf" in yaml_text and "1: ref_square" in yaml_text


def test_vision_eval_lin_ccc_and_area_calibration(tmp_path):
    y_true = [0.5, 2.0, 5.0, 12.0, 25.0, 40.0]
    y_pred_good = [0.6, 2.1, 4.8, 12.4, 24.5, 39.2]
    res_good = ve.lin_ccc(y_true, y_pred_good)
    assert res_good["lin_ccc"] >= 0.99
    assert res_good["meets_target"] is True

    # Viés sistemático grande derruba CCC mesmo com Pearson alto
    y_pred_biased = [v + 15.0 for v in y_true]
    res_bad = ve.lin_ccc(y_true, y_pred_biased)
    assert res_bad["pearson_r"] > 0.99
    assert res_bad["lin_ccc"] < 0.80
    assert res_bad["meets_target"] is False

    area_ok = ve.area_calibration_error([40.0, 50.0, 35.0], [41.0, 49.0, 36.0])
    assert area_ok["mean_rel_error_pct"] < 5.0
    assert area_ok["meets_target"] is True

    area_bad = ve.area_calibration_error([40.0, 50.0], [46.0, 58.0])
    assert area_bad["meets_target"] is False

    # Notebook Colab é JSON válido
    nb = json.loads((ROOT / "legacy" / "train_yolo_seg.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4 and len(nb["cells"]) >= 5
