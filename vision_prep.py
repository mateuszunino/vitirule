#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision_prep.py
==============
Preparação de datasets e pré-anotação para a Fase 1 (visão computacional sem
experimento), seguindo estritamente a seção 8 do SKILL.md:

* Estágio A (`stage_a_leaf.pt`): 0 `leaf`, 1 `ref_square`
* Estágio B (`stage_b_lesion.pt`): 0 `necrosis`, 1 `chlorosis`
* Recortes do estágio B sempre com fundo pintado de cinza 114 (igual ao
  `vision_pipeline.py` linha 816 na inferência).
* Divisão treino/validação SEMPRE por grupo (vaso, planta, vídeo ou fonte de
  imagem), NUNCA por frame. Quando há IDs de vaso, `V05`, `V10`, `V15` e `V20`
  vão obrigatoriamente para validação.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import cv2
import numpy as np

import vision_pipeline as vp

log = logging.getLogger("vision_prep")

STAGE_A_CLASSES = {0: "leaf", 1: "ref_square"}
STAGE_B_CLASSES = {0: "necrosis", 1: "chlorosis"}
VAL_POTS = frozenset({"V05", "V10", "V15", "V20"})
POT_RE = re.compile(r"\b(V(?:0[1-9]|1\d|20))\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Conversão máscara binária <-> polígonos YOLO-seg
# --------------------------------------------------------------------------
def mask_to_yolo_polygons(
    mask: np.ndarray,
    class_id: int,
    min_area_px: int = 20,
    epsilon_frac: float = 0.002,
) -> list[str]:
    """Converte uma máscara binária (H, W) em linhas normalizadas YOLO-seg."""
    h, w = mask.shape[:2]
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines: list[str] = []
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area_px:
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon_frac * peri, True)
        pts = approx.reshape(-1, 2)
        if len(pts) < 3:
            continue
        coords = []
        for x, y in pts:
            coords.append(f"{np.clip(x / w, 0.0, 1.0):.6f}")
            coords.append(f"{np.clip(y / h, 0.0, 1.0):.6f}")
        lines.append(f"{int(class_id)} " + " ".join(coords))
    return lines


def yolo_polygons_to_masks(
    label_path: str | Path,
    height: int,
    width: int,
    n_classes: int = 2,
) -> dict[int, np.ndarray]:
    """Reconstrói máscaras binárias (0/1) por classe a partir de um `.txt` YOLO-seg."""
    masks = {c: np.zeros((height, width), dtype=np.uint8) for c in range(n_classes)}
    path = Path(label_path)
    if not path.is_file():
        return masks
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.strip().split()
        if len(parts) < 7:
            continue
        cls_id = int(parts[0])
        if cls_id not in masks:
            continue
        nums = [float(v) for v in parts[1:]]
        pts = np.array(
            [[round(nums[i] * width), round(nums[i + 1] * height)] for i in range(0, len(nums) - 1, 2)],
            dtype=np.int32,
        )
        if len(pts) >= 3:
            cv2.fillPoly(masks[cls_id], [pts], 1)
    return masks


# --------------------------------------------------------------------------
# Recorte do Estágio B com fundo cinza 114 (SKILL.md seção 8)
# --------------------------------------------------------------------------
def build_stage_b_crop(
    image_bgr: np.ndarray,
    leaf_mask: np.ndarray,
    necrosis_mask: Optional[np.ndarray] = None,
    chlorosis_mask: Optional[np.ndarray] = None,
    crop_pad: float = 0.04,
) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Gera o recorte da folha com fundo pintado de cinza 114 — idêntico ao que
    `VisionPipeline._stage_b` entrega na inferência (`vision_pipeline.py:816`).
    """
    h, w = leaf_mask.shape[:2]
    ys, xs = np.where(leaf_mask > 0)
    if len(xs) == 0:
        raise ValueError("leaf_mask vazia; não é possível gerar recorte do estágio B")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    pad = int(crop_pad * max(x1 - x0, y1 - y0))
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w, x1 + pad), min(h, y1 + pad)

    crop = image_bgr[y0:y1, x0:x1].copy()
    leaf_crop = leaf_mask[y0:y1, x0:x1] > 0
    crop[~leaf_crop] = 114

    nec_crop = None
    chl_crop = None
    if necrosis_mask is not None:
        nec_crop = ((necrosis_mask[y0:y1, x0:x1] > 0) & leaf_crop).astype(np.uint8)
    if chlorosis_mask is not None:
        chl_raw = (chlorosis_mask[y0:y1, x0:x1] > 0) & leaf_crop
        if nec_crop is not None:
            chl_raw = chl_raw & (nec_crop == 0)   # pixel com as duas classes conta como necrose
        chl_crop = chl_raw.astype(np.uint8)
    return crop, nec_crop, chl_crop


# --------------------------------------------------------------------------
# Pré-anotação usando a reserva clássica do `vision_pipeline.py`
# --------------------------------------------------------------------------
def preannotate_image(
    image_path: str | Path,
    out_dir: str | Path,
    cfg: Optional[vp.PipelineConfig] = None,
) -> dict[str, Any]:
    """
    Pré-anota uma imagem para revisão manual (SAM/CVAT/Roboflow), gerando:
    * `stage_a/images/` e `stage_a/labels/` (0 `leaf`, 1 `ref_square`)
    * `stage_b/images/` e `stage_b/labels/` (recorte cinza 114; 0 `necrosis`, 1 `chlorosis`)
    """
    cfg = cfg or vp.PipelineConfig(weights_a=None, weights_b=None)
    img_path = Path(image_path)
    img = cv2.imread(str(img_path))
    if img is None:
        raise ValueError(f"não foi possível ler a imagem: {img_path}")

    leaf, square = vp.classical_stage_a(img, cfg)
    out = Path(out_dir)
    for stage in ("stage_a", "stage_b"):
        (out / stage / "images").mkdir(parents=True, exist_ok=True)
        (out / stage / "labels").mkdir(parents=True, exist_ok=True)

    stem = img_path.stem
    stage_a_lines: list[str] = []
    if leaf is not None:
        stage_a_lines.extend(mask_to_yolo_polygons(leaf, 0))
    if square is not None:
        stage_a_lines.extend(mask_to_yolo_polygons(square, 1))

    cv2.imwrite(str(out / "stage_a" / "images" / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    (out / "stage_a" / "labels" / f"{stem}.txt").write_text("\n".join(stage_a_lines), encoding="utf-8")

    stage_b_created = False
    if leaf is not None and int((leaf > 0).sum()) > 0:
        nec, chl = vp.classical_stage_b(img, leaf, cfg)
        crop, nec_c, chl_c = build_stage_b_crop(img, leaf, nec, chl, crop_pad=cfg.crop_pad)
        stage_b_lines: list[str] = []
        if nec_c is not None:
            stage_b_lines.extend(mask_to_yolo_polygons(nec_c, 0, min_area_px=cfg.min_lesion_px))
        if chl_c is not None:
            stage_b_lines.extend(mask_to_yolo_polygons(chl_c, 1, min_area_px=cfg.min_lesion_px))
        cv2.imwrite(str(out / "stage_b" / "images" / f"{stem}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
        (out / "stage_b" / "labels" / f"{stem}.txt").write_text("\n".join(stage_b_lines), encoding="utf-8")
        stage_b_created = True

    return {
        "image": img_path.name,
        "leaf_found": leaf is not None,
        "ref_square_found": square is not None,
        "stage_a_polygons": len(stage_a_lines),
        "stage_b_created": stage_b_created,
    }


def preannotate_video(
    video_path: str | Path,
    out_dir: str | Path,
    cfg: Optional[vp.PipelineConfig] = None,
) -> list[dict[str, Any]]:
    """Extrai keyframes nítidos via `vision_pipeline` e pré-anota cada keyframe."""
    cfg = cfg or vp.PipelineConfig(weights_a=None, weights_b=None)
    vpath = Path(video_path)
    scan = vp.scan_video(str(vpath), cfg)
    indices, _ = vp.select_keyframes(scan["scores"], scan["hashes"], cfg)
    frames = vp.load_frames(str(vpath), indices)

    tmp_frames = Path(out_dir) / "_raw_keyframes"
    tmp_frames.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for idx in indices:
        if idx not in frames:
            continue
        frame_file = tmp_frames / f"{vpath.stem}_f{idx:04d}.jpg"
        cv2.imwrite(str(frame_file), frames[idx], [cv2.IMWRITE_JPEG_QUALITY, 95])
        summaries.append(preannotate_image(frame_file, out_dir, cfg=cfg))
    return summaries


# --------------------------------------------------------------------------
# Divisão treino/validação estritamente por grupo (sem vazamento de frames)
# --------------------------------------------------------------------------
def infer_group_id(filename: str) -> str:
    """
    Extrai o grupo de divisão:
    * Se o nome contém um vaso (`V01`-`V20`), retorna o código do vaso (`V05`).
    * Se contém sufixo de frame (`_f0012`), remove o sufixo para agrupar pelo vídeo.
    * Caso contrário, usa o stem sem sufixo numérico final.
    """
    stem = Path(filename).stem
    m = POT_RE.search(stem.replace("-", " ").replace("_", " "))
    if m:
        return m.group(1).upper()
    cleaned = re.sub(r"_f\d+$", "", stem, flags=re.IGNORECASE)
    return cleaned


def split_by_group(
    items: Sequence[dict[str, Any]],
    val_fraction: float = 0.20,
    group_key: str = "group_id",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Separa itens em `(train, val)` garantindo interseção ZERO de grupos entre
    treino e validação. Vasos `V05`, `V10`, `V15` e `V20` vão sempre para `val`
    (SKILL.md seção 8).
    """
    if not 0.0 < val_fraction < 1.0:
        raise ValueError("val_fraction deve ficar entre 0 e 1")

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for item in items:
        gid = str(item[group_key])
        if gid.upper() in VAL_POTS:
            is_val = True
        elif POT_RE.fullmatch(gid.upper()):
            is_val = False
        else:
            digest = hashlib.sha256(gid.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") / float(1 << 32)
            is_val = bucket < val_fraction
        (val if is_val else train).append(item)

    # Garante que nenhum grupo apareça nos dois lados
    train_groups = {str(x[group_key]) for x in train}
    val_groups = {str(x[group_key]) for x in val}
    assert train_groups.isdisjoint(val_groups), "vazamento de grupos entre treino e validação"
    return train, val


def write_yolo_dataset_yaml(dataset_root: str | Path, stage: str) -> Path:
    """Escreve `stage_a.yaml` ou `stage_b.yaml` com os índices exatos da seção 8."""
    if stage not in ("stage_a", "stage_b"):
        raise ValueError("stage deve ser 'stage_a' ou 'stage_b'")
    classes = STAGE_A_CLASSES if stage == "stage_a" else STAGE_B_CLASSES
    root = Path(dataset_root).resolve()
    yaml_path = root / f"{stage}.yaml"
    lines = [
        f"path: {root.as_posix()}",
        "train: images/train",
        "val: images/val",
        "names:",
    ]
    for idx, name in sorted(classes.items()):
        lines.append(f"  {idx}: {name}")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def organize_yolo_split(
    source_dir: str | Path,
    dest_dir: str | Path,
    stage: str,
    val_fraction: float = 0.20,
) -> dict[str, Any]:
    """Organiza `images/` e `labels/` em `images/{train,val}` e `labels/{train,val}` por grupo."""
    src = Path(source_dir)
    dst = Path(dest_dir)
    images = sorted(
        p for p in (src / "images").glob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    )
    items = [
        {
            "image": img,
            "label": src / "labels" / f"{img.stem}.txt",
            "group_id": infer_group_id(img.name),
        }
        for img in images
    ]
    train, val = split_by_group(items, val_fraction=val_fraction)
    for split_name, subset in (("train", train), ("val", val)):
        (dst / "images" / split_name).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split_name).mkdir(parents=True, exist_ok=True)
        for item in subset:
            shutil.copy2(item["image"], dst / "images" / split_name / item["image"].name)
            if item["label"].is_file():
                shutil.copy2(item["label"], dst / "labels" / split_name / item["label"].name)
            else:
                (dst / "labels" / split_name / f"{item['image'].stem}.txt").write_text("", encoding="utf-8")

    yaml_path = write_yolo_dataset_yaml(dst, stage)
    return {
        "stage": stage,
        "yaml": str(yaml_path),
        "n_train": len(train),
        "n_val": len(val),
        "train_groups": sorted({x["group_id"] for x in train}),
        "val_groups": sorted({x["group_id"] for x in val}),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preparação de datasets YOLO-seg (Fase 1).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("preannotate", help="pré-anota imagens ou vídeos com a reserva clássica")
    p_pre.add_argument("input_path", help="arquivo de imagem/vídeo ou pasta")
    p_pre.add_argument("--out-dir", required=True)

    p_spl = sub.add_parser("split", help="divide images/ e labels/ por grupo sem vazamento")
    p_spl.add_argument("--source-dir", required=True)
    p_spl.add_argument("--dest-dir", required=True)
    p_spl.add_argument("--stage", choices=("stage_a", "stage_b"), required=True)
    p_spl.add_argument("--val-fraction", type=float, default=0.20)

    args = parser.parse_args(argv)
    if args.cmd == "preannotate":
        inp = Path(args.input_path)
        results = []
        if inp.is_dir():
            for p in sorted(inp.glob("*")):
                if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    results.append(preannotate_image(p, args.out_dir))
                elif p.suffix.lower() in (".mp4", ".mov", ".avi"):
                    results.extend(preannotate_video(p, args.out_dir))
        elif inp.suffix.lower() in (".mp4", ".mov", ".avi"):
            results = preannotate_video(inp, args.out_dir)
        else:
            results = [preannotate_image(inp, args.out_dir)]
        print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
    elif args.cmd == "split":
        info = organize_yolo_split(args.source_dir, args.dest_dir, args.stage, val_fraction=args.val_fraction)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
