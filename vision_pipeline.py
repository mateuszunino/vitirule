#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision_pipeline.py
==================
Severidade foliar a partir de vídeo curto (1080p, 30 fps, 4-5 s) de uma folha
marcada de tomateiro sobre EVA azul-royal ou cinza, com um quadrado de
referência de 2 x 2 cm no mesmo plano da folha.

Fluxo
-----
1. Keyframes: nitidez por variância do Laplaciano, um candidato por trecho do
   vídeo, descarte de frames borrados e de quase duplicatas (dHash).
2. Estágio A: máscara da folha e do quadrado de referência (YOLO-seg com as
   classes `leaf` e `ref_square`), mais a calibração px -> cm².
3. Estágio B: lesões dentro da máscara da folha (YOLO-seg com as classes
   `necrosis` e `chlorosis`), em recorte de alta resolução.
4. Alinhamento dos keyframes ao frame de referência e voto por pixel. Uma
   lesão vista em cinco frames entra uma vez só na conta.
5. Severidade (%) = área lesionada / área total da folha x 100, além das áreas
   absolutas em mm² e cm².

Decisões matemáticas
--------------------
* Nitidez: Var(Laplaciano) do recorte central, depois de um desfoque 3x3 que
  tira o ruído do sensor. O limiar é relativo ao percentil 90 do próprio vídeo,
  porque o valor absoluto depende da textura da cena e da exposição.
* Calibração por área: cm²/px = 4 cm² / área do quadrado em px. Com a câmera
  inclinada em um ângulo theta, a área aparente do quadrado e a da folha
  encolhem pelo mesmo fator cos(theta) quando os dois estão no mesmo plano.
  A razão corrige a inclinação em primeira ordem, coisa que medir um lado do
  quadrado não faz.
* Severidade é razão de áreas na mesma imagem. Por isso não depende da
  calibração, e um erro no quadrado só afeta mm² e cm².
* Agregação: transformação de similaridade (4 graus de liberdade) de cada
  keyframe para o frame de referência, estimada por ORB + RANSAC, com reserva
  por momentos da máscara. O voto majoritário por pixel elimina reflexo
  especular e falso positivo que aparecem em um único frame. Sem alinhamento
  confiável, vale a mediana das severidades por frame.
* O desvio-padrão entre frames sai no JSON como `severity_sd_pct` e vira o
  peso da observação no módulo de assimilação.

Memória (GTX 1660 Super, 6 GB)
------------------------------
* Estágio A em imgsz 640 e lote de até 4. Estágio B em imgsz 1024 e lote 2,
  só no recorte da folha. Os dois modelos `s` ocupam bem menos de 3 GB.
* FP16: as placas GTX 16xx têm defeito conhecido de meia precisão no PyTorch,
  com saída NaN. O pipeline compara FP32 e FP16 na própria placa antes de
  ligar `half` e guarda o resultado em cache. Se divergir, roda em FP32.
* Falta de memória: o lote cai pela metade, depois o imgsz cai em passos de
  25 % até `min_imgsz`.

Enquanto os pesos não estiverem treinados, `allow_classical_fallback=True`
usa limiares de cor (Lab/HSV). Serve para pré-anotar imagens e testar o
encadeamento, não para o dado do ensaio: o JSON sai com a flag
`classical_fallback_*`.

Uso
---
    python vision_pipeline.py V11-F2_20261201T0930.mp4 \
        --weights-a models/stage_a_leaf.pt --weights-b models/stage_b_lesion.pt \
        --captured-at 2026-12-01T09:30:00-03:00 --debug-dir debug/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import cv2
import numpy as np

log = logging.getLogger("vision_pipeline")

SCHEMA_VERSION = "1.0"
ID_PATTERN = re.compile(r"(V(?:0[1-9]|1\d|20))[-_ ]?F([1-9])", re.IGNORECASE)


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    # Pesos. None ou arquivo ausente aciona a reserva clássica, se permitida.
    weights_a: Optional[str] = "models/stage_a_leaf.pt"
    weights_b: Optional[str] = "models/stage_b_lesion.pt"
    allow_classical_fallback: bool = True

    # Nomes de classe aceitos em cada modelo.
    leaf_classes: tuple = ("leaf", "folha")
    square_classes: tuple = ("ref_square", "referencia", "square")
    necrosis_classes: tuple = ("necrosis", "necrose")
    chlorosis_classes: tuple = ("chlorosis", "clorose", "halo")

    # Inferência
    device: str = "auto"            # "auto" | "cpu" | "cuda:0"
    half: str = "auto"              # "auto" | "on" | "off"
    imgsz_a: int = 640
    imgsz_b: int = 1024
    min_imgsz: int = 512
    batch_a: int = 4
    batch_b: int = 2
    conf_a: float = 0.35
    conf_b: float = 0.20
    iou: float = 0.60
    max_det: int = 300
    tile_b: str = "auto"            # "auto" | "on" | "off"
    tile_overlap: float = 0.15

    # Keyframes
    max_keyframes: int = 5
    min_keyframes: int = 3
    blur_rel_threshold: float = 0.55   # fração do percentil 90 de nitidez
    sharpness_roi: float = 0.70        # recorte central usado na medida
    min_frame_gap: int = 5
    dedup_hamming: int = 3             # distância máxima do dHash de 64 bits

    # Geometria e calibração
    ref_square_side_cm: float = 2.0
    min_squareness: float = 0.85
    leaf_min_frac: float = 0.01        # área mínima da folha, fração do frame
    crop_pad: float = 0.04

    # Alinhamento
    align_min_iou: float = 0.88
    align_min_inliers: int = 12
    align_max_side: int = 960

    # Reserva clássica (OpenCV, Lab em 8 bits com a e b deslocados de 128)
    cl_necrosis_a_min: int = 126
    cl_necrosis_l_max: int = 150
    cl_dark_l_max: int = 40
    cl_chlorosis_a_min: int = 114
    cl_chlorosis_b_min: int = 160
    min_lesion_px: int = 12

    def validate(self) -> None:
        if not 1 <= self.min_keyframes <= self.max_keyframes:
            raise ValueError("min_keyframes deve ficar entre 1 e max_keyframes")
        for name in ("imgsz_a", "imgsz_b", "min_imgsz"):
            if getattr(self, name) % 32:
                raise ValueError(f"{name} precisa ser múltiplo de 32")


# --------------------------------------------------------------------------
# Estruturas internas
# --------------------------------------------------------------------------
@dataclass
class Keyframe:
    index: int
    sharpness: float
    image: np.ndarray = field(repr=False, default=None)


@dataclass
class Calibration:
    cm2_per_px: float
    px_per_cm: float
    side_px: float
    squareness: float
    quad: np.ndarray = field(repr=False, default=None)


@dataclass
class FrameAnalysis:
    kf: Keyframe
    leaf: Optional[np.ndarray] = field(repr=False, default=None)        # uint8 0/1
    necrosis: Optional[np.ndarray] = field(repr=False, default=None)
    chlorosis: Optional[np.ndarray] = field(repr=False, default=None)
    calib: Optional[Calibration] = None
    aligned: bool = False
    align_iou: Optional[float] = None
    align_method: Optional[str] = None
    touches_border: bool = False

    @property
    def valid(self) -> bool:
        return self.leaf is not None and int(self.leaf.sum()) > 0

    def severity(self) -> Optional[dict]:
        if not self.valid or self.necrosis is None:
            return None
        return _severity_from_masks(self.leaf, self.necrosis, self.chlorosis)


# --------------------------------------------------------------------------
# 1. Keyframes
# --------------------------------------------------------------------------
def laplacian_sharpness(gray: np.ndarray, roi: float = 0.70) -> float:
    """Variância do Laplaciano no recorte central. Cai com desfoque de movimento."""
    h, w = gray.shape[:2]
    dy, dx = int(h * (1 - roi) / 2), int(w * (1 - roi) / 2)
    crop = gray[dy:h - dy, dx:w - dx]
    crop = cv2.GaussianBlur(crop, (3, 3), 0)
    return float(cv2.Laplacian(crop, cv2.CV_64F, ksize=3).var())


def dhash64(gray: np.ndarray) -> int:
    """Hash de diferença de 64 bits. Frames quase idênticos diferem em poucos bits."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def scan_video(path: str, cfg: PipelineConfig) -> dict:
    """Primeira passada: nitidez e hash de cada frame, sem guardar as imagens."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"não foi possível abrir o vídeo: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    scores, hashes = [], []
    width = height = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scores.append(laplacian_sharpness(gray, cfg.sharpness_roi))
        hashes.append(dhash64(gray))
    cap.release()
    if not scores:
        raise IOError(f"vídeo sem frames legíveis: {path}")
    return {"scores": np.asarray(scores), "hashes": hashes, "fps": float(fps),
            "width": int(width), "height": int(height), "n_frames": len(scores)}


def select_keyframes(scores: np.ndarray, hashes: Sequence[int],
                     cfg: PipelineConfig) -> tuple[list[int], dict]:
    """
    Divide o vídeo em `max_keyframes` trechos e pega o frame mais nítido de
    cada um, desde que passe do limiar relativo de nitidez. Depois remove
    quase duplicatas, sem descer abaixo de `min_keyframes`.
    """
    n = len(scores)
    ref = float(np.percentile(scores, 90))
    sharp = scores >= cfg.blur_rel_threshold * ref
    chosen: list[int] = []
    for segment in np.array_split(np.arange(n), min(cfg.max_keyframes, n)):
        cand = segment[sharp[segment]]
        if cand.size:
            chosen.append(int(cand[np.argmax(scores[cand])]))

    if len(chosen) < cfg.min_keyframes:
        for i in np.argsort(-scores):
            if all(abs(int(i) - c) >= cfg.min_frame_gap for c in chosen):
                chosen.append(int(i))
            if len(chosen) >= cfg.min_keyframes:
                break

    chosen.sort(key=lambda i: -scores[i])
    kept: list[int] = []
    dropped = 0
    for i in chosen:
        duplicate = any(_hamming(hashes[i], hashes[k]) <= cfg.dedup_hamming for k in kept)
        if duplicate and len(kept) >= cfg.min_keyframes:
            dropped += 1
            continue
        kept.append(i)
    info = {"sharpness_p90": ref, "n_blurry": int((~sharp).sum()),
            "n_duplicates_dropped": dropped}
    return sorted(kept), info


def load_frames(path: str, indices: Sequence[int]) -> dict[int, np.ndarray]:
    """Segunda passada sequencial. O seek por frame em H.264 não é confiável."""
    wanted = set(int(i) for i in indices)
    frames: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(path)
    i = 0
    last = max(wanted)
    while i <= last:
        ok, frame = cap.read()
        if not ok:
            break
        if i in wanted:
            frames[i] = frame
        i += 1
    cap.release()
    return frames


# --------------------------------------------------------------------------
# Utilidades de máscara
# --------------------------------------------------------------------------
def _fill_holes(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, contours, -1, 1, thickness=cv2.FILLED)
    return out


def _keep_major_components(mask: np.ndarray, rel_min: float = 0.05) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 2:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = np.flatnonzero(areas >= rel_min * areas.max()) + 1
    return np.isin(labels, keep).astype(np.uint8)


def _remove_small(mask: np.ndarray, min_px: int) -> np.ndarray:
    if min_px <= 1:
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    keep = np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] >= min_px) + 1
    return np.isin(labels, keep).astype(np.uint8)


def _bbox(mask: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _touches_border(mask: np.ndarray, margin: int = 2) -> bool:
    return bool(mask[:margin].any() or mask[-margin:].any()
                or mask[:, :margin].any() or mask[:, -margin:].any())


def _severity_from_masks(leaf: np.ndarray, necrosis: np.ndarray,
                         chlorosis: Optional[np.ndarray]) -> dict:
    leaf_px = int(leaf.sum())
    nec = (necrosis > 0) & (leaf > 0)
    chl = ((chlorosis > 0) & (leaf > 0) & ~nec) if chlorosis is not None else np.zeros_like(nec)
    nec_px, chl_px = int(nec.sum()), int(chl.sum())
    lesion_px = nec_px + chl_px
    pct = lambda v: 100.0 * v / leaf_px if leaf_px else float("nan")
    return {"leaf_px": leaf_px, "lesion_px": lesion_px, "necrosis_px": nec_px,
            "chlorosis_px": chl_px, "severity_pct": pct(lesion_px),
            "necrosis_pct": pct(nec_px), "chlorosis_pct": pct(chl_px)}


def calibrate_from_square(mask: np.ndarray, side_cm: float) -> Optional[Calibration]:
    """cm²/px pela área do quadrado. Ver a nota sobre inclinação no cabeçalho."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    (_, _), (w, h), _ = cv2.minAreaRect(contour)
    if min(w, h) < 8 or area <= 0:
        return None
    aspect = min(w, h) / max(w, h)
    extent = min(area / (w * h), 1.0)
    side_px = math.sqrt(area)
    quad = cv2.boxPoints(cv2.minAreaRect(contour))
    return Calibration(cm2_per_px=side_cm ** 2 / area, px_per_cm=side_px / side_cm,
                       side_px=side_px, squareness=float(aspect * extent), quad=quad)


# --------------------------------------------------------------------------
# Reserva clássica (sem pesos treinados)
# --------------------------------------------------------------------------
def classical_stage_a(bgr: np.ndarray, cfg: PipelineConfig) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Separa a folha e o quadrado do fundo EVA por cor. A cor do fundo é a
    mediana da moldura externa do frame. Em fundo azul a regra é de matiz,
    que resiste a sombra. Nos demais, distância em Lab com limiar de Otsu.
    Devolve (máscara da folha, máscara do quadrado).
    """
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    ring = np.zeros((h, w), bool)
    m = max(4, int(0.04 * min(h, w)))
    ring[:m] = ring[-m:] = True
    ring[:, :m] = ring[:, -m:] = True
    bg_h, bg_s = np.median(hsv[..., 0][ring]), np.median(hsv[..., 1][ring])

    if bg_s > 70 and 90 <= bg_h <= 135:
        dh = np.abs(hsv[..., 0].astype(np.int16) - int(bg_h))
        background = (dh <= 15) & (hsv[..., 1] > 60)
    else:
        bg_lab = np.median(lab[ring].reshape(-1, 3), axis=0)
        dist = np.linalg.norm(lab.astype(np.float32) - bg_lab.astype(np.float32), axis=2)
        dist8 = np.clip(dist * 2.0, 0, 255).astype(np.uint8)
        thr, _ = cv2.threshold(dist8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        background = dist8 <= max(thr, 30)

    fg = (~background).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    green = (hsv[..., 0] >= 30) & (hsv[..., 0] <= 95) & (hsv[..., 1] > 40)
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    skin = ((ycc[..., 1] >= 135) & (ycc[..., 1] <= 175) & (ycc[..., 2] >= 80)
            & (ycc[..., 2] <= 130) & (hsv[..., 2] > 120) & ~green)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    frame_area = h * w
    leaf_mask = square_mask = None
    best_leaf, best_square = 0.0, 0.0
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 0.0004 * frame_area:
            continue
        comp = (labels == i).astype(np.uint8)
        green_frac = float(green[comp > 0].mean())
        # candidato a quadrado de referência: quatro vértices, convexo, quase quadrado
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)
        approx = cv2.approxPolyDP(cnt, 0.04 * cv2.arcLength(cnt, True), True)
        (_, _), (rw, rh), _ = cv2.minAreaRect(cnt)
        if (len(approx) == 4 and cv2.isContourConvex(approx) and min(rw, rh) > 8
                and area < 0.06 * frame_area and green_frac < 0.2):
            score = (min(rw, rh) / max(rw, rh)) * min(cv2.contourArea(cnt) / (rw * rh), 1.0)
            if score > max(best_square, 0.80):
                best_square, square_mask = score, comp
                continue
        if area >= cfg.leaf_min_frac * frame_area and green_frac > 0.25:
            score = area * (0.15 + green_frac)
            if score > best_leaf:
                best_leaf, leaf_mask = score, comp

    if leaf_mask is not None:
        leaf_mask = (leaf_mask.astype(bool) & ~skin).astype(np.uint8)
        # a abertura corta pecíolo e pontas de dedo, que são estruturas finas
        k = max(5, int(0.035 * math.sqrt(leaf_mask.sum()))) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        opened = cv2.morphologyEx(leaf_mask, cv2.MORPH_OPEN, kernel)
        leaf_mask = _fill_holes(_keep_major_components(opened))
    return leaf_mask, square_mask


def classical_stage_b(bgr: np.ndarray, leaf: np.ndarray, cfg: PipelineConfig) -> tuple[np.ndarray, np.ndarray]:
    """Necrose e clorose por limiar em Lab. Só para pré-anotação e testes."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    inside = leaf > 0
    necrosis = inside & (((a >= cfg.cl_necrosis_a_min) & (L <= cfg.cl_necrosis_l_max))
                         | (L <= cfg.cl_dark_l_max))
    chlorosis = inside & ~necrosis & (a >= cfg.cl_chlorosis_a_min) & (b >= cfg.cl_chlorosis_b_min)
    kernel = np.ones((3, 3), np.uint8)
    necrosis = cv2.morphologyEx(necrosis.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    chlorosis = cv2.morphologyEx(chlorosis.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    return _remove_small(necrosis, cfg.min_lesion_px), _remove_small(chlorosis, cfg.min_lesion_px)


# --------------------------------------------------------------------------
# Inferência YOLO com controle de memória
# --------------------------------------------------------------------------
class YoloRunner:
    """Carrega um modelo de segmentação, decide FP16 e trata falta de memória."""

    def __init__(self, weights: str, device: str, half_mode: str, cache_dir: Path):
        import torch
        from ultralytics import YOLO

        self.torch = torch
        self.weights = str(weights)
        self.model = YOLO(self.weights)
        # Versões recentes do ultralytics trocaram `half=True` por `quantize=16`.
        try:
            from ultralytics.cfg import DEFAULT_CFG_DICT
            self._uses_quantize = "quantize" in DEFAULT_CFG_DICT
        except ImportError:
            self._uses_quantize = False
        self.device = self._resolve_device(device)
        self.fp16_reason = "cpu"
        self.half = False
        if self.device != "cpu":
            torch.backends.cudnn.benchmark = True
            self.half, self.fp16_reason = self._decide_half(half_mode, cache_dir)
        log.info("modelo %s em %s, half=%s (%s)", Path(weights).name, self.device,
                 self.half, self.fp16_reason)

    def _resolve_device(self, device: str) -> str:
        if device == "auto":
            return "cuda:0" if self.torch.cuda.is_available() else "cpu"
        return device

    def _decide_half(self, mode: str, cache_dir: Path) -> tuple[bool, str]:
        env = os.environ.get("VISION_HALF")
        if env in ("0", "1"):
            return env == "1", "variável VISION_HALF"
        if mode == "off":
            return False, "desligado na configuração"
        if mode == "on":
            return True, "forçado na configuração"
        torch = self.torch
        key = "|".join([torch.cuda.get_device_name(0), torch.__version__, Path(self.weights).name])
        cache_file = cache_dir / "fp16_check.json"
        cache: dict = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                cache = {}
        if key not in cache:
            cache[key] = self._fp16_selftest()
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, indent=2))
        return bool(cache[key]), "autoteste FP32 x FP16"

    def _fp16_selftest(self) -> bool:
        """
        Compara a saída bruta da rede em FP32 e em FP16 para a mesma entrada.
        Nas GTX 16xx a meia precisão devolve NaN qualquer que seja a entrada.
        """
        import copy
        torch = self.torch
        try:
            net = copy.deepcopy(self.model.model).to(self.device).eval()
            gen = torch.Generator(device="cpu").manual_seed(0)
            x = torch.rand(1, 3, 320, 320, generator=gen).to(self.device)

            def first_tensor(out):
                while isinstance(out, (list, tuple)):
                    out = out[0]
                return out.float()

            with torch.inference_mode():
                y32 = first_tensor(net.float()(x.float()))
                y16 = first_tensor(net.half()(x.half()))
            if not torch.isfinite(y16).all():
                return False
            rel = (y16 - y32).abs().mean() / y32.abs().mean().clamp_min(1e-6)
            return bool(rel < 0.05)
        except Exception as exc:  # qualquer falha desliga a meia precisão
            log.warning("autoteste FP16 falhou (%s); usando FP32", exc)
            return False
        finally:
            torch.cuda.empty_cache()

    def predict(self, images: list[np.ndarray], imgsz: int, batch: int, conf: float,
                cfg: PipelineConfig) -> tuple[list, dict]:
        """Inferência em lotes. Reduz lote e depois imgsz se faltar memória."""
        torch = self.torch
        results: list = []
        if self._uses_quantize:
            precision = {"quantize": 16} if self.half else {}
        else:
            precision = {"half": self.half}
        i = 0
        while i < len(images):
            chunk = images[i:i + batch]
            try:
                out = self.model.predict(chunk, imgsz=imgsz, conf=conf, iou=cfg.iou,
                                         device=self.device, retina_masks=True,
                                         max_det=cfg.max_det, verbose=False, **precision)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower():
                    raise
                torch.cuda.empty_cache()
                if batch > 1:
                    batch = max(1, batch // 2)
                elif imgsz > cfg.min_imgsz:
                    imgsz = max(cfg.min_imgsz, int(imgsz * 0.75) // 32 * 32)
                else:
                    raise
                log.warning("memória insuficiente: lote=%d, imgsz=%d", batch, imgsz)
                continue
            results.extend(out)
            i += len(chunk)
        if self.device != "cpu":
            torch.cuda.empty_cache()
        return results, {"imgsz": imgsz, "batch": batch}


def masks_by_class(result, groups: dict[str, Sequence[str]]) -> dict[str, list[tuple[np.ndarray, float]]]:
    """Agrupa as máscaras de um Results por classe: {grupo: [(máscara 0/1, conf)]}."""
    h, w = result.orig_shape
    out: dict[str, list] = {g: [] for g in groups}
    if result.masks is None or len(result.boxes) == 0:
        return out
    names = result.names
    classes = result.boxes.cls.int().tolist()
    confs = result.boxes.conf.float().tolist()
    data = result.masks.data
    same_shape = tuple(data.shape[-2:]) == (h, w)
    polygons = None if same_shape else result.masks.xy
    for i, (c, p) in enumerate(zip(classes, confs)):
        name = str(names[c]).lower()
        group = next((g for g, aliases in groups.items() if name in aliases), None)
        if group is None:
            continue
        if same_shape:
            mask = (data[i] > 0.5).cpu().numpy().astype(np.uint8)
        else:  # sem retina_masks a máscara vem no tamanho da entrada da rede
            mask = np.zeros((h, w), np.uint8)
            if len(polygons[i]) >= 3:
                cv2.fillPoly(mask, [polygons[i].astype(np.int32)], 1)
        out[group].append((mask, float(p)))
    return out


# --------------------------------------------------------------------------
# 4. Alinhamento entre keyframes
# --------------------------------------------------------------------------
def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def _similarity_orb(src: np.ndarray, src_mask: np.ndarray, dst: np.ndarray,
                    dst_mask: np.ndarray, cfg: PipelineConfig) -> Optional[np.ndarray]:
    h, w = src.shape[:2]
    s = min(1.0, cfg.align_max_side / max(h, w))
    size = (int(w * s), int(h * s))
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    kernel = np.ones((9, 9), np.uint8)

    def prep(img, mask):
        gray = clahe.apply(cv2.cvtColor(cv2.resize(img, size), cv2.COLOR_BGR2GRAY))
        m = cv2.dilate(cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST), kernel) * 255
        return gray, m

    g1, m1 = prep(src, src_mask)
    g2, m2 = prep(dst, dst_mask)
    orb = cv2.ORB_create(nfeatures=1500)
    k1, d1 = orb.detectAndCompute(g1, m1)
    k2, d2 = orb.detectAndCompute(g2, m2)
    if d1 is None or d2 is None or len(k1) < cfg.align_min_inliers or len(k2) < cfg.align_min_inliers:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < cfg.align_min_inliers:
        return None
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    M, inliers = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC,
                                             ransacReprojThreshold=3.0,
                                             maxIters=2000, confidence=0.995)
    if M is None or inliers is None or int(inliers.sum()) < cfg.align_min_inliers:
        return None
    M = M.copy()
    M[:, 2] /= s        # translação de volta para a resolução original
    return M


def _similarity_moments(src_mask: np.ndarray, dst_mask: np.ndarray) -> list[np.ndarray]:
    """Similaridade por centroide, eixo principal e razão de áreas. Duas hipóteses (0 e 180 graus)."""
    def pose(mask):
        mom = cv2.moments(mask, binaryImage=True)
        if mom["m00"] == 0:
            return None
        cx, cy = mom["m10"] / mom["m00"], mom["m01"] / mom["m00"]
        theta = 0.5 * math.atan2(2 * mom["mu11"], mom["mu20"] - mom["mu02"])
        return cx, cy, theta, mom["m00"]

    a, b = pose(src_mask), pose(dst_mask)
    if a is None or b is None:
        return []
    scale = math.sqrt(b[3] / a[3])
    out = []
    for flip in (0.0, math.pi):
        rot = b[2] - a[2] + flip
        c, s = scale * math.cos(rot), scale * math.sin(rot)
        tx = b[0] - (c * a[0] - s * a[1])
        ty = b[1] - (s * a[0] + c * a[1])
        out.append(np.float32([[c, -s, tx], [s, c, ty]]))
    return out


def align_to_reference(frame: FrameAnalysis, ref: FrameAnalysis, cfg: PipelineConfig) -> bool:
    """Leva as máscaras do frame para a geometria do frame de referência."""
    h, w = ref.leaf.shape
    candidates: list[tuple[str, np.ndarray]] = []
    M = _similarity_orb(frame.kf.image, frame.leaf, ref.kf.image, ref.leaf, cfg)
    if M is not None:
        candidates.append(("orb_ransac", M))
    candidates += [("moments", m) for m in _similarity_moments(frame.leaf, ref.leaf)]

    best: tuple[float, Optional[str], Optional[np.ndarray]] = (0.0, None, None)
    for name, M in candidates:
        warped = cv2.warpAffine(frame.leaf, M, (w, h), flags=cv2.INTER_NEAREST)
        score = _iou(warped, ref.leaf)
        if score > best[0]:
            best = (score, name, M)
    score, name, M = best
    frame.align_iou, frame.align_method = score, name
    if M is None or score < cfg.align_min_iou:
        frame.aligned = False
        return False
    warp = lambda m: cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_NEAREST)
    frame._warped = (warp(frame.leaf), warp(frame.necrosis), warp(frame.chlorosis))
    frame.aligned = True
    return True


def consensus_masks(frames: list[FrameAnalysis], ref: FrameAnalysis) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Voto majoritário por pixel entre o frame de referência e os alinhados."""
    stack = [(ref.leaf, ref.necrosis, ref.chlorosis)]
    stack += [f._warped for f in frames if f is not ref and f.aligned]
    n = len(stack)
    need = n // 2 + 1
    vote = lambda idx: (np.sum([s[idx] for s in stack], axis=0) >= need).astype(np.uint8)
    leaf = vote(0)
    lesion_any = (np.sum([np.maximum(s[1], s[2]) for s in stack], axis=0) >= need)
    necrosis = vote(1)
    # pixel lesionado na maioria dos frames, mas sem maioria de necrose, conta como clorose
    chlorosis = (lesion_any & (necrosis == 0)).astype(np.uint8)
    return leaf, necrosis, chlorosis, n


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
class VisionPipeline:
    def __init__(self, cfg: Optional[PipelineConfig] = None):
        self.cfg = cfg or PipelineConfig()
        self.cfg.validate()
        self.cache_dir = Path(os.environ.get("TOMATO_DSS_CACHE", Path.home() / ".cache" / "tomato_dss"))
        self._runner_a: Optional[YoloRunner] = None
        self._runner_b: Optional[YoloRunner] = None
        self._loaded = False

    # ---- carga dos modelos ------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        self._runner_a = self._make_runner(self.cfg.weights_a, "A")
        self._runner_b = self._make_runner(self.cfg.weights_b, "B")
        self._loaded = True

    def _make_runner(self, weights: Optional[str], stage: str) -> Optional[YoloRunner]:
        if weights and Path(weights).is_file():
            return YoloRunner(weights, self.cfg.device, self.cfg.half, self.cache_dir)
        if not self.cfg.allow_classical_fallback:
            raise FileNotFoundError(f"pesos do estágio {stage} não encontrados: {weights}")
        log.warning("estágio %s sem pesos (%s): usando a reserva clássica", stage, weights)
        return None

    # ---- estágio A ----------------------------------------------------------
    def _stage_a(self, frames: list[FrameAnalysis], meta: dict) -> None:
        cfg = self.cfg
        if self._runner_a is None:
            for f in frames:
                leaf, square = classical_stage_a(f.kf.image, cfg)
                self._store_stage_a(f, leaf, square)
            meta["stage_a"] = "classical"
            return
        images = [f.kf.image for f in frames]
        results, used = self._runner_a.predict(images, cfg.imgsz_a, cfg.batch_a, cfg.conf_a, cfg)
        meta.update(stage_a="yolo", imgsz_a=used["imgsz"], batch_a=used["batch"])
        groups = {"leaf": cfg.leaf_classes, "square": cfg.square_classes}
        for f, res in zip(frames, results):
            found = masks_by_class(res, groups)
            leaf = None
            if found["leaf"]:
                # folha composta: une os folíolos detectados e descarta fragmentos soltos
                leaf = np.clip(np.sum([m for m, _ in found["leaf"]], axis=0), 0, 1).astype(np.uint8)
                leaf = _keep_major_components(leaf)
            square = max(found["square"], key=lambda t: t[1])[0] if found["square"] else None
            self._store_stage_a(f, leaf, square)

    def _store_stage_a(self, f: FrameAnalysis, leaf: Optional[np.ndarray],
                       square: Optional[np.ndarray]) -> None:
        h, w = f.kf.image.shape[:2]
        if leaf is not None and leaf.sum() >= self.cfg.leaf_min_frac * h * w:
            if square is not None:
                leaf = (leaf.astype(bool) & ~square.astype(bool)).astype(np.uint8)
            f.leaf = leaf
            f.touches_border = _touches_border(leaf)
        if square is not None:
            f.calib = calibrate_from_square(square, self.cfg.ref_square_side_cm)

    # ---- estágio B ----------------------------------------------------------
    def _tiles(self, w: int, h: int) -> list[tuple[int, int, int, int]]:
        cfg = self.cfg
        mode = cfg.tile_b
        if mode == "off" or (mode == "auto" and max(w, h) <= 1.6 * cfg.imgsz_b):
            return [(0, 0, w, h)]
        nx = 2 if w >= h else 1
        ny = 2 if h > w else 1
        if mode == "on" and min(w, h) > cfg.imgsz_b:
            nx = ny = 2
        tw, th = math.ceil(w / nx), math.ceil(h / ny)
        ox, oy = int(tw * cfg.tile_overlap), int(th * cfg.tile_overlap)
        tiles = []
        for j in range(ny):
            for i in range(nx):
                x0, y0 = max(0, i * tw - ox), max(0, j * th - oy)
                x1, y1 = min(w, (i + 1) * tw + ox), min(h, (j + 1) * th + oy)
                tiles.append((x0, y0, x1, y1))
        return tiles

    def _stage_b(self, frames: list[FrameAnalysis], meta: dict) -> None:
        cfg = self.cfg
        valid = [f for f in frames if f.valid]
        if self._runner_b is None:
            for f in valid:
                f.necrosis, f.chlorosis = classical_stage_b(f.kf.image, f.leaf, cfg)
            meta["stage_b"] = "classical"
            return

        crops, origin = [], []          # origin: (frame, x0, y0) de cada recorte
        for f in valid:
            h, w = f.leaf.shape
            x0, y0, x1, y1 = _bbox(f.leaf)
            pad = int(cfg.crop_pad * max(x1 - x0, y1 - y0))
            x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
            crop = f.kf.image[y0:y1, x0:x1].copy()
            crop[f.leaf[y0:y1, x0:x1] == 0] = 114     # fundo neutro: a rede só vê a folha
            f.necrosis = np.zeros((h, w), np.uint8)
            f.chlorosis = np.zeros((h, w), np.uint8)
            for tx0, ty0, tx1, ty1 in self._tiles(x1 - x0, y1 - y0):
                crops.append(crop[ty0:ty1, tx0:tx1])
                origin.append((f, x0 + tx0, y0 + ty0))

        results, used = self._runner_b.predict(crops, cfg.imgsz_b, cfg.batch_b, cfg.conf_b, cfg)
        meta.update(stage_b="yolo", imgsz_b=used["imgsz"], batch_b=used["batch"],
                    tiles_per_frame=round(len(crops) / max(len(valid), 1), 2))
        groups = {"necrosis": cfg.necrosis_classes, "chlorosis": cfg.chlorosis_classes}
        for (f, ox, oy), res in zip(origin, results):
            found = masks_by_class(res, groups)
            ch, cw = res.orig_shape
            for key, target in (("necrosis", f.necrosis), ("chlorosis", f.chlorosis)):
                for mask, _ in found[key]:
                    np.maximum(target[oy:oy + ch, ox:ox + cw], mask, out=target[oy:oy + ch, ox:ox + cw])
        for f in valid:
            inside = f.leaf > 0
            f.necrosis = _remove_small((f.necrosis.astype(bool) & inside).astype(np.uint8), cfg.min_lesion_px)
            f.chlorosis = _remove_small((f.chlorosis.astype(bool) & inside & (f.necrosis == 0)).astype(np.uint8),
                                        cfg.min_lesion_px)

    # ---- execução completa --------------------------------------------------
    def process(self, video_path: str, leaf_id: Optional[str] = None,
                captured_at: Optional[str] = None, debug_dir: Optional[str] = None) -> dict:
        t0 = time.perf_counter()
        cfg = self.cfg
        path = Path(video_path)
        flags: list[str] = []

        leaf_id, pot_id = self._ids(path, leaf_id)
        scan = scan_video(str(path), cfg)
        indices, kinfo = select_keyframes(scan["scores"], scan["hashes"], cfg)
        images = load_frames(str(path), indices)
        frames = [FrameAnalysis(Keyframe(i, float(scan["scores"][i]), images[i]))
                  for i in indices if i in images]
        if len(frames) < cfg.min_keyframes:
            flags.append("few_keyframes")
        if kinfo["n_blurry"] > 0.8 * scan["n_frames"]:
            flags.append("low_sharpness")

        self._load()
        meta: dict[str, Any] = {
            "weights_a": Path(cfg.weights_a).name if self._runner_a else None,
            "weights_b": Path(cfg.weights_b).name if self._runner_b else None,
            "device": self._runner_a.device if self._runner_a else (
                self._runner_b.device if self._runner_b else "cpu"),
            "half": bool((self._runner_a and self._runner_a.half) or (self._runner_b and self._runner_b.half)),
        }
        self._stage_a(frames, meta)
        self._stage_b(frames, meta)
        for stage in ("a", "b"):
            if meta.get(f"stage_{stage}") == "classical":
                flags.append(f"classical_fallback_stage_{stage}")
        if cfg.half == "auto" and meta["device"] != "cpu" and not meta["half"]:
            flags.append("fp16_disabled")

        valid = [f for f in frames if f.valid and f.necrosis is not None]
        result = self._base_result(path, scan, kinfo, leaf_id, pot_id, captured_at, meta)
        if not valid:
            flags.append("no_leaf")
            return self._finish(result, frames, flags, t0, ok=False)

        # referência: o frame válido mais nítido que tenha calibração
        with_calib = [f for f in valid if f.calib is not None]
        ref = max(with_calib or valid, key=lambda f: f.kf.sharpness)
        ref.aligned, ref.align_iou, ref.align_method = True, 1.0, "reference"
        for f in valid:
            if f is not ref:
                align_to_reference(f, ref, cfg)
        leaf, necrosis, chlorosis, n_used = consensus_masks(valid, ref)

        per_frame = [f.severity() for f in valid]
        sev_values = np.array([s["severity_pct"] for s in per_frame])
        if n_used >= 2:
            agg = _severity_from_masks(leaf, necrosis, chlorosis)
            method, calib = "consensus", ref.calib
            cm2 = calib.cm2_per_px if calib else None
            areas_px = (agg["leaf_px"], agg["lesion_px"], agg["necrosis_px"], agg["chlorosis_px"])
        else:
            if len(valid) > 1:
                flags.append("alignment_failed")
            method, calib = "median", ref.calib
            med = lambda key: float(np.median([s[key] for s in per_frame]))
            agg = {k: med(k) for k in ("severity_pct", "necrosis_pct", "chlorosis_pct")}
            cm2 = None
            areas_px = None
            if with_calib:   # áreas físicas: mediana das áreas de cada frame calibrado
                def phys(key):
                    return float(np.median([f.severity()[key] * f.calib.cm2_per_px for f in with_calib]))
                areas_cm2 = tuple(phys(k) for k in ("leaf_px", "lesion_px", "necrosis_px", "chlorosis_px"))

        if calib is None:
            flags.append("no_calibration")
        elif calib.squareness < cfg.min_squareness:
            flags.append("calibration_tilt")
        if any(f.touches_border for f in valid):
            flags.append("leaf_touches_border")
        sd = float(np.std(sev_values, ddof=1)) if len(sev_values) > 1 else None
        if sd is not None and sd > max(1.0, 0.25 * agg["severity_pct"]):
            flags.append("high_frame_disagreement")

        if method == "consensus" and cm2 is not None:
            areas_cm2 = tuple(a * cm2 for a in areas_px)
        elif method == "consensus" or not with_calib:
            areas_cm2 = (None, None, None, None)

        r4 = lambda v: None if v is None else round(float(v), 4)
        result.update({
            "severity_pct": r4(agg["severity_pct"]),
            "severity_sd_pct": r4(sd),
            "necrosis_pct": r4(agg["necrosis_pct"]),
            "chlorosis_pct": r4(agg["chlorosis_pct"]),
            "leaf_area_cm2": r4(areas_cm2[0]),
            "lesion_area_mm2": r4(None if areas_cm2[1] is None else areas_cm2[1] * 100.0),
            "necrosis_area_mm2": r4(None if areas_cm2[2] is None else areas_cm2[2] * 100.0),
            "chlorosis_area_mm2": r4(None if areas_cm2[3] is None else areas_cm2[3] * 100.0),
            "calibration": None if calib is None else {
                "px_per_cm": r4(calib.px_per_cm), "ref_square_side_px": r4(calib.side_px),
                "ref_square_side_cm": cfg.ref_square_side_cm, "squareness": r4(calib.squareness),
                "ok": bool(calib.squareness >= cfg.min_squareness)},
            "aggregation": {"method": method, "n_keyframes": len(frames), "n_valid": len(valid),
                            "n_aligned": int(sum(f.aligned for f in valid)),
                            "reference_frame": ref.kf.index},
        })
        if debug_dir:
            self._write_debug(Path(debug_dir), path.stem, ref, leaf, necrosis, chlorosis)
        return self._finish(result, frames, flags, t0, ok=True)

    # ---- montagem do resultado ---------------------------------------------
    @staticmethod
    def _ids(path: Path, leaf_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        match = ID_PATTERN.search(leaf_id or path.stem)
        if not match:
            return leaf_id, None
        pot = match.group(1).upper()
        return f"{pot}-F{match.group(2)}", pot

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    def _base_result(self, path, scan, kinfo, leaf_id, pot_id, captured_at, meta) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "leaf_id": leaf_id, "pot_id": pot_id, "captured_at": captured_at,
            "video": {"file": path.name, "sha256": self._sha256(path), "n_frames": scan["n_frames"],
                      "fps": round(scan["fps"], 3), "width": scan["width"], "height": scan["height"]},
            "severity_pct": None, "severity_sd_pct": None, "necrosis_pct": None, "chlorosis_pct": None,
            "leaf_area_cm2": None, "lesion_area_mm2": None, "necrosis_area_mm2": None,
            "chlorosis_area_mm2": None, "calibration": None, "aggregation": None,
            "keyframe_selection": {"sharpness_p90": round(kinfo["sharpness_p90"], 2),
                                   "n_blurry": kinfo["n_blurry"],
                                   "n_duplicates_dropped": kinfo["n_duplicates_dropped"]},
            "method": meta,
        }

    @staticmethod
    def _finish(result: dict, frames: list[FrameAnalysis], flags: list[str], t0: float, ok: bool) -> dict:
        keyframes = []
        for f in frames:
            sev = f.severity()
            keyframes.append({
                "frame_index": f.kf.index, "sharpness": round(f.kf.sharpness, 2),
                "leaf_found": f.valid, "calibrated": f.calib is not None,
                "severity_pct": None if sev is None else round(sev["severity_pct"], 4),
                "aligned": bool(f.aligned),
                "align_iou": None if f.align_iou is None else round(f.align_iou, 4),
                "align_method": f.align_method})
        blocking = {"no_leaf", "classical_fallback_stage_a", "classical_fallback_stage_b",
                    "leaf_touches_border", "high_frame_disagreement", "few_keyframes"}
        result["keyframes"] = keyframes
        result["quality"] = {"ok": bool(ok and not (blocking & set(flags))), "flags": sorted(set(flags))}
        result["processing_ms"] = int((time.perf_counter() - t0) * 1000)
        return result

    @staticmethod
    def _write_debug(folder: Path, stem: str, ref: FrameAnalysis, leaf, necrosis, chlorosis) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        canvas = ref.kf.image.copy()
        for mask, color in ((leaf, (0, 255, 0)), (chlorosis, (0, 255, 255)), (necrosis, (0, 0, 255))):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(canvas, contours, -1, color, 2)
        if ref.calib is not None:
            cv2.polylines(canvas, [ref.calib.quad.astype(np.int32)], True, (255, 0, 255), 2)
        cv2.imwrite(str(folder / f"{stem}_overlay.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])


def process_video(video_path: str, config: Optional[PipelineConfig] = None, **kwargs) -> dict:
    """Atalho para uso único. No Flask, crie um VisionPipeline só e reutilize."""
    return VisionPipeline(config).process(video_path, **kwargs)


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Severidade foliar a partir de vídeo curto.")
    parser.add_argument("video")
    parser.add_argument("--leaf-id", help="ex.: V11-F2. Se ausente, lido do nome do arquivo.")
    parser.add_argument("--captured-at", help="ISO 8601 com fuso, ex.: 2026-12-01T09:30:00-03:00")
    parser.add_argument("--weights-a", default=PipelineConfig.weights_a)
    parser.add_argument("--weights-b", default=PipelineConfig.weights_b)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--half", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--imgsz-a", type=int, default=PipelineConfig.imgsz_a)
    parser.add_argument("--imgsz-b", type=int, default=PipelineConfig.imgsz_b)
    parser.add_argument("--no-fallback", action="store_true",
                        help="falha se os pesos não existirem, em vez de usar limiares de cor")
    parser.add_argument("--debug-dir")
    parser.add_argument("--output", help="grava o JSON neste arquivo")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = PipelineConfig(weights_a=args.weights_a, weights_b=args.weights_b, device=args.device,
                         half=args.half, imgsz_a=args.imgsz_a, imgsz_b=args.imgsz_b,
                         allow_classical_fallback=not args.no_fallback)
    result = VisionPipeline(cfg).process(args.video, leaf_id=args.leaf_id,
                                         captured_at=args.captured_at, debug_dir=args.debug_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["quality"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
