#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/export_brand_png.py
===========================
Exports all vector SVG brand assets in `docs/brand/` to crisp PNGs at exact
target pixel dimensions using headless Chrome/Edge (zero extra Python deps).

Regenerates:
  - vitirule-icon-1024.png, vitirule-icon-512.png, vitirule-icon-32.png
  - vitirule-icon-a-512.png, vitirule-icon-b-512.png, vitirule-icon-c-512.png
  - vitirule-icon-a-32.png, vitirule-icon-b-32.png, vitirule-icon-c-32.png
  - vitirule-icon-options.png (960 x 440 comparison sheet)
  - vitirule-social.png (1280 x 640, < 1 MB)
  - vitirule-card.png (1200 x 627)
  - banner-linkedin-pt.png (1584 x 396)
  - banner-linkedin-en.png (1584 x 396)
  - banner-linkedin-safezone-preview.png (1584 x 396)
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "docs" / "brand"

EXPORT_SPECS: list[tuple[str, str, int, int, str]] = [
    # (svg_name, png_name, width, height, background_css)
    ("vitirule-icon.svg", "vitirule-icon-1024.png", 1024, 1024, "transparent"),
    ("vitirule-icon.svg", "vitirule-icon-512.png", 512, 512, "transparent"),
    ("vitirule-icon.svg", "vitirule-icon-32.png", 32, 32, "transparent"),
    ("vitirule-social.svg", "vitirule-social.png", 1280, 640, "#f8fafc"),
    ("vitirule-card.svg", "vitirule-card.png", 1200, 627, "#f8fafc"),
    ("banner-linkedin-pt.svg", "banner-linkedin-pt.png", 1584, 396, "#f8fafc"),
    ("banner-linkedin-en.svg", "banner-linkedin-en.png", 1584, 396, "#f8fafc"),
    ("banner-linkedin-safezone-preview.svg", "banner-linkedin-safezone-preview.png", 1584, 396, "#f8fafc"),
]


def _find_browser() -> str:
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(p).is_file():
            return p
    raise FileNotFoundError("Chrome or Edge executable not found for headless PNG export.")


def _png_dimensions(png_path: Path) -> tuple[int, int]:
    header = png_path.read_bytes()[:24]
    w, h = struct.unpack(">II", header[16:24])
    return int(w), int(h)


def export_one(browser: str, svg_path: Path, png_path: Path, w: int, h: int, bg: str) -> tuple[int, int, int]:
    svg_text = svg_path.read_text(encoding="utf-8")
    html_doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        "<style>"
        f"*{{margin:0;padding:0;box-sizing:border-box;}}"
        f"html,body{{width:{w}px;height:{h}px;overflow:hidden;background:{bg};}}"
        f"svg{{display:block;width:{w}px;height:{h}px;}}"
        "</style></head>"
        f"<body>{svg_text}</body></html>"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        html_file = Path(tmpdir) / "render.html"
        html_file.write_text(html_doc, encoding="utf-8")
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={w},{h}",
            f"--screenshot={png_path}",
        ]
        if bg == "transparent":
            cmd.append("--default-background-color=00000000")
        cmd.append(html_file.resolve().as_uri())
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not png_path.is_file():
            raise RuntimeError(f"Failed exporting {png_path.name}: {proc.stderr}")
    aw, ah = _png_dimensions(png_path)
    return aw, ah, png_path.stat().st_size


def main() -> int:
    browser = _find_browser()
    for svg_name, png_name, w, h, bg in EXPORT_SPECS:
        svg_path = BRAND_DIR / svg_name
        if not svg_path.is_file():
            print(f"[skip] missing {svg_name}")
            continue
        png_path = BRAND_DIR / png_name
        aw, ah, size = export_one(browser, svg_path, png_path, w, h, bg)
        ok = "OK" if (aw == w and ah == h) else f"MISMATCH({aw}x{ah})"
        print(f"  {png_name:38s} {aw:4d}x{ah:<4d}  {size/1024:6.1f} KB  [{ok}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
