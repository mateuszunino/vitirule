#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/build_brand_assets.py
=============================
Generates hand-crafted, flat vector SVG brand assets for `vitirule` under
`docs/brand/`, using the exact report palette and real data from the frozen
semi-real INRAE sensor OSSE:

Palette:
  - Teal (station / rule)     : #0f766e
  - Burnt orange (alert/drop) : #c2410c
  - Slate dark (primary text) : #0f172a
  - Slate muted (secondary)   : #64748b
  - Off-white canvas          : #f8fafc / #ffffff

Outputs in docs/brand/:
  - vitirule-icon-a.svg       (Variation A: teal vine leaf + orange water drop)
  - vitirule-icon-b.svg       (Variation B: teal water drop + white vine leaf)
  - vitirule-icon-c.svg       (Variation C: teal vine leaf + ruler midrib w/ 3 ticks + orange drop)
  - vitirule-icon.svg         (Active default icon; currently Variation C)
  - vitirule-icon-mono.svg    (Monochrome slate #0f172a version)
  - vitirule-logo.svg         (Horizontal logo: icon + lowercase `vitirule`)
  - vitirule-logo-variants.svg(Comparison strip of A / B / C icons + horizontal logos)
  - vitirule-social.svg       (GitHub social preview, 1280 x 640, real Figure 1 data)
  - vitirule-card.svg         (LinkedIn project card, 1200 x 627, real Figure 1 data)
  - banner-linkedin-pt.svg    (LinkedIn banner PT, 1584 x 396, real Figure 2 LWD bars)
  - banner-linkedin-en.svg    (LinkedIn banner EN, 1584 x 396, real Figure 2 LWD bars)
  - banner-linkedin-safezone-preview.svg (Review overlay showing desktop photo & mobile crops)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "docs" / "brand"
BRAND_DIR.mkdir(parents=True, exist_ok=True)

TEAL = "#0f766e"
ORANGE = "#c2410c"
DARK = "#0f172a"
MUTED = "#64748b"
BG = "#f8fafc"
WHITE = "#ffffff"
FONT = "Inter, 'Source Sans 3', 'Segoe UI', Arial, sans-serif"

# Clean 5-lobed grapevine leaf silhouette in a 128x128 coordinate space
# Bold, symmetric, flat geometry designed to remain recognizable at 32x32 px.
LEAF_PATH = (
    "M 64 11 "
    "C 68 18, 76 28, 79 37 "
    "C 89 34, 102 35, 112 42 "
    "C 108 53, 100 62, 91 67 "
    "C 100 74, 104 84, 101 95 "
    "C 91 101, 79 100, 70 93 "
    "L 64 88 "
    "L 58 93 "
    "C 49 100, 37 101, 27 95 "
    "C 24 84, 28 74, 37 67 "
    "C 28 62, 20 53, 16 42 "
    "C 26 35, 39 34, 49 37 "
    "C 52 28, 60 18, 64 11 Z"
)

# Clean water droplet centered at (0, 0), height ~44, width ~30
def _drop_path(cx: float, cy: float, rx: float, top_h: float, bot_h: float) -> str:
    return (
        f"M {cx:.1f} {cy - top_h:.1f} "
        f"C {cx + rx * 0.55:.1f} {cy - top_h * 0.25:.1f}, "
        f"{cx + rx:.1f} {cy + bot_h * 0.15:.1f}, "
        f"{cx + rx:.1f} {cy + bot_h * 0.42:.1f} "
        f"A {rx:.1f} {bot_h * 0.58:.1f} 0 1 1 "
        f"{cx - rx:.1f} {cy + bot_h * 0.42:.1f} "
        f"C {cx - rx:.1f} {cy + bot_h * 0.15:.1f}, "
        f"{cx - rx * 0.55:.1f} {cy - top_h * 0.25:.1f}, "
        f"{cx:.1f} {cy - top_h:.1f} Z"
    )


def _icon_a_inner(leaf_color: str = TEAL, drop_color: str = ORANGE, cutout: str = WHITE) -> str:
    """Variation A: 5-lobed teal vine leaf + burnt-orange water drop resting on it."""
    drop = _drop_path(75.0, 62.0, rx=16.5, top_h=24.0, bot_h=21.0)
    return "\n".join([
        f'<path d="{LEAF_PATH}" fill="{leaf_color}"/>',
        f'<line x1="64" y1="86" x2="64" y2="117" stroke="{leaf_color}" stroke-width="8" stroke-linecap="round"/>',
        # Crisp negative-space cutout around the droplet for 32px legibility
        f'<path d="{drop}" fill="{drop_color}" stroke="{cutout}" stroke-width="5.5" stroke-linejoin="round"/>',
    ])


def _icon_b_inner(drop_color: str = TEAL, leaf_color: str = WHITE, accent_color: str | None = ORANGE) -> str:
    """Variation B: teal water drop containing a crisp white 5-lobed vine leaf."""
    outer_drop = _drop_path(64.0, 66.0, rx=45.0, top_h=56.0, bot_h=52.0)
    parts = [
        f'<path d="{outer_drop}" fill="{drop_color}"/>',
        # Scale and center the 5-lobed leaf inside the droplet belly
        f'<g transform="translate(64 78) scale(0.56) translate(-64 -60)">',
        f'  <path d="{LEAF_PATH}" fill="{leaf_color}"/>',
        f'  <line x1="64" y1="86" x2="64" y2="114" stroke="{leaf_color}" stroke-width="9" stroke-linecap="round"/>',
        "</g>",
    ]
    if accent_color:
        # Small interval dot near droplet tip tying to the rule concept
        parts.append(f'<circle cx="64" cy="34" r="5.2" fill="{accent_color}"/>')
    return "\n".join(parts)


def _icon_c_inner(leaf_color: str = TEAL, mark_color: str = WHITE, drop_color: str = ORANGE) -> str:
    """Variation C: 5-lobed teal vine leaf with central midrib as a 3-tick ruler + small orange droplet."""
    # Small crisp droplet tucked cleanly at the upper-right with breathing room
    drop = _drop_path(103.0, 20.0, rx=10.5, top_h=14.5, bot_h=12.5)
    return "\n".join([
        f'<path d="{LEAF_PATH}" fill="{leaf_color}"/>',
        f'<line x1="64" y1="86" x2="64" y2="117" stroke="{leaf_color}" stroke-width="8" stroke-linecap="round"/>',
        # Central ruler midrib (bold enough to read clearly at 32x32)
        f'<line x1="64" y1="27" x2="64" y2="88" stroke="{mark_color}" stroke-width="6.5" stroke-linecap="round"/>',
        # Three interval graduation ticks across the midrib
        f'<line x1="51" y1="43" x2="77" y2="43" stroke="{mark_color}" stroke-width="5.8" stroke-linecap="round"/>',
        f'<line x1="46" y1="60" x2="82" y2="60" stroke="{mark_color}" stroke-width="5.8" stroke-linecap="round"/>',
        f'<line x1="51" y1="77" x2="77" y2="77" stroke="{mark_color}" stroke-width="5.8" stroke-linecap="round"/>',
        # Orange water drop accent
        f'<path d="{drop}" fill="{drop_color}"/>',
    ])


def _wrap_square_icon(inner: str, bg: str | None = None) -> str:
    bg_rect = f'<rect width="128" height="128" rx="22" fill="{bg}"/>' if bg else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="512" height="512">\n'
        + (f"  {bg_rect}\n" if bg_rect else "")
        + f"  {inner}\n"
        + "</svg>\n"
    )


def build_icons_and_logos(default_variant: str = "a") -> None:
    mono_map = {
        "a": _icon_a_inner(leaf_color=DARK, drop_color=DARK, cutout=WHITE),
        "b": _icon_b_inner(drop_color=DARK, leaf_color=WHITE, accent_color=None),
        "c": _icon_c_inner(leaf_color=DARK, mark_color=WHITE, drop_color=DARK),
    }
    color_map = {
        "a": _icon_a_inner(),
        "b": _icon_b_inner(),
        "c": _icon_c_inner(),
    }
    (BRAND_DIR / "vitirule-icon.svg").write_text(_wrap_square_icon(color_map[default_variant]), encoding="utf-8")
    (BRAND_DIR / "vitirule-icon-mono.svg").write_text(_wrap_square_icon(mono_map[default_variant]), encoding="utf-8")

    # Horizontal logo for README top (width=360, height=96 -> clean at width="160")
    logo_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 96" width="360" height="96" '
        f'style="font-family:{FONT}">\n'
        f'  <g transform="translate(4 4) scale(0.6875)">\n'
        f"    {color_map[default_variant]}\n"
        f"  </g>\n"
        f'  <text x="104" y="67" font-size="56" font-weight="700" letter-spacing="-1.6" fill="{DARK}">vitirule</text>\n'
        f"</svg>\n"
    )
    (BRAND_DIR / "vitirule-logo.svg").write_text(logo_svg, encoding="utf-8")


def _load_real_pareto_points() -> dict:
    raw = json.loads((ROOT / "data" / "fase2" / "semireal_inrae_osse.json").read_text(encoding="utf-8"))
    pooled = raw["inrae_semireal_sensor_truth"]["pooled"]
    cals = sorted(pooled["calendars"], key=lambda c: c["sprays_mean"])
    rules = {r["strategy"]: r for r in pooled["rules"]}
    return {"calendars": cals, "om_v1": rules["om_v1_T10"], "om_v2": rules["om_v2_T10"]}


def _build_social_svg(width: int, height: int, out_name: str, default_variant: str = "c") -> None:
    """Builds 1280x640 GitHub social preview or 1200x627 LinkedIn card with real Figure 1 data."""
    pts = _load_real_pareto_points()
    cals = pts["calendars"]
    om_v1 = pts["om_v1"]
    icon_inner = {"a": _icon_a_inner(), "b": _icon_b_inner(), "c": _icon_c_inner()}[default_variant]

    pad = 54
    left_w = int(width * 0.51)
    card_x = pad + left_w + 18
    card_y = pad + 8
    card_w = width - card_x - pad
    card_h = height - 2 * pad - 16

    # Mini Figure 1 plot coordinates inside right card
    pl, pr, pt_m, pb = card_x + 62, card_x + card_w - 28, card_y + 70, card_y + card_h - 68
    pw, ph = pr - pl, pb - pt_m
    xmin, xmax = 5.4, 11.6
    ymin, ymax = 82.0, 162.0

    def sx(v: float) -> float:
        return pl + (v - xmin) / (xmax - xmin) * pw

    def sy(v: float) -> float:
        return pb - (v - ymin) / (ymax - ymin) * ph

    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="font-family:{FONT};background:{BG}">',
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        # Clean top accent bar (teal + burnt orange)
        f'<rect x="0" y="0" width="{int(width*0.72)}" height="7" fill="{TEAL}"/>',
        f'<rect x="{int(width*0.72)}" y="0" width="{width - int(width*0.72)}" height="7" fill="{ORANGE}"/>',
        # Left column: Horizontal logo
        f'<g transform="translate({pad} {pad+16}) scale(0.76)">{icon_inner}</g>',
        f'<text x="{pad+114}" y="{pad+86}" font-size="68" font-weight="800" letter-spacing="-2" fill="{DARK}">vitirule</text>',
        # Headline (wrapped cleanly, generous margin >= 40px)
        f'<text x="{pad}" y="{pad+178}" font-size="31" font-weight="700" fill="{DARK}">Testing weather-driven spray rules</text>',
        f'<text x="{pad}" y="{pad+220}" font-size="31" font-weight="700" fill="{DARK}">against grapevine downy mildew</text>',
        f'<text x="{pad}" y="{pad+262}" font-size="31" font-weight="700" fill="{TEAL}">before the field</text>',
        # Divider
        f'<line x1="{pad}" y1="{pad+298}" x2="{pad+96}" y2="{pad+298}" stroke="{ORANGE}" stroke-width="4" stroke-linecap="round"/>',
        # Secondary metadata line (exact wording from briefing)
        f'<text x="{pad}" y="{pad+344}" font-size="18.5" font-weight="500" fill="{MUTED}">Open, reproducible protocol · 80,392 sensor hours</text>',
        f'<text x="{pad}" y="{pad+372}" font-size="18.5" font-weight="500" fill="{MUTED}">5 wine regions · 2016–2025</text>',
        # Subtle footer handle
        f'<text x="{pad}" y="{height - pad - 10}" font-size="15.5" font-weight="600" fill="{MUTED}">github.com/mateuszunino/vitirule</text>',
        # Right column: White card with real simplified Figure 1
        f'<rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="14" fill="{WHITE}" stroke="#e2e8f0" stroke-width="1.5"/>',
        f'<text x="{card_x+24}" y="{card_y+32}" font-size="15.5" font-weight="700" fill="{DARK}">Semi-real INRAE sensor OSSE (N = 1,200)</text>',
        f'<text x="{card_x+24}" y="{card_y+51}" font-size="12" fill="{MUTED}">Pooled fixed calendars vs. frozen rule (T = 10)</text>',
    ]

    # Subtle horizontal gridlines
    for yv in (90, 110, 130, 150):
        yy = sy(yv)
        elems.append(f'<line x1="{pl}" y1="{yy:.1f}" x2="{pr}" y2="{yy:.1f}" stroke="#f1f5f9" stroke-width="1.2"/>')
        elems.append(f'<text x="{pl-10}" y="{yy+4:.1f}" text-anchor="end" font-size="11.5" fill="{MUTED}">{yv}</text>')

    # X axis ticks
    for xv in (6, 7, 8, 9, 10, 11):
        xx = sx(xv)
        elems.append(f'<line x1="{xx:.1f}" y1="{pb}" x2="{xx:.1f}" y2="{pb+5}" stroke="#cbd5e1" stroke-width="1.2"/>')
        elems.append(f'<text x="{xx:.1f}" y="{pb+20}" text-anchor="middle" font-size="11.5" fill="{MUTED}">{xv}</text>')

    # Clean axes
    elems.append(f'<line x1="{pl}" y1="{pt_m}" x2="{pl}" y2="{pb}" stroke="#cbd5e1" stroke-width="1.3"/>')
    elems.append(f'<line x1="{pl}" y1="{pb}" x2="{pr}" y2="{pb}" stroke="#cbd5e1" stroke-width="1.3"/>')
    elems.append(f'<text x="{(pl+pr)/2:.1f}" y="{pb+44}" text-anchor="middle" font-size="12.5" font-weight="600" fill="{MUTED}">Mean sprays / season</text>')
    elems.append(f'<text x="{card_x+18}" y="{(pt_m+pb)/2:.1f}" text-anchor="middle" font-size="12.5" font-weight="600" fill="{MUTED}" transform="rotate(-90 {card_x+18} {(pt_m+pb)/2:.1f})">Mean AUDPC</text>')

    # Calendar frontier polyline (real data)
    cal_poly = " ".join(f"{sx(c['sprays_mean']):.1f},{sy(c['aacpd_mean']):.1f}" for c in cals)
    elems.append(f'<polyline points="{cal_poly}" fill="none" stroke="{DARK}" stroke-width="3.2"/>')
    cal_labels = {
        "cal_14d": ("14d", 0, -14),
        "cal_12d": ("12d", 6, -13),
        "cal_10d": ("10d", 10, -12),
        "cal_7d": ("7d", -2, -14),
    }
    for c in cals:
        cx, cy = sx(c["sprays_mean"]), sy(c["aacpd_mean"])
        lbl, dx, dy = cal_labels[c["strategy"]]
        elems.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.8" fill="{DARK}" stroke="{WHITE}" stroke-width="1.8"/>')
        elems.append(f'<text x="{cx+dx:.1f}" y="{cy+dy:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{DARK}">{lbl}</text>')

    # Dashed vertical gap showing exact real -18.95 AUDPC below frontier at 6.77 sprays
    rx, ry = sx(om_v1["sprays_mean"]), sy(om_v1["aacpd_mean"])
    fy = sy(om_v1["calendar_frontier_aacpd"])
    elems.append(f'<line x1="{rx:.1f}" y1="{fy:.1f}" x2="{rx:.1f}" y2="{ry:.1f}" stroke="{ORANGE}" stroke-width="2.2" stroke-dasharray="4,3"/>')

    # om_v1_T10 highlighted diamond (real data: 6.77 sprays, 121.4 AUDPC)
    d_pts = f"{rx:.1f},{ry-10:.1f} {rx+10:.1f},{ry:.1f} {rx:.1f},{ry+10:.1f} {rx-10:.1f},{ry:.1f}"
    elems.append(f'<polygon points="{d_pts}" fill="{TEAL}" stroke="{WHITE}" stroke-width="2"/>')

    # Clean callout badge placed cleanly in open bottom-left quadrant (zero overlap with frontier line!)
    bx, by = pl + 14, pb - 66
    elems.append(f'<line x1="{rx:.1f}" y1="{ry+11:.1f}" x2="{bx+62:.1f}" y2="{by:.1f}" stroke="{TEAL}" stroke-width="1.4" stroke-dasharray="3,2"/>')
    elems.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="184" height="52" rx="8" fill="{BG}" stroke="{TEAL}" stroke-width="1.5"/>')
    elems.append(f'<text x="{bx+12:.1f}" y="{by+21:.1f}" font-size="13" font-weight="700" fill="{TEAL}">om_v1_T10 (6.77 sprays)</text>')
    elems.append(f'<text x="{bx+12:.1f}" y="{by+40:.1f}" font-size="12" font-weight="600" fill="{DARK}">−19.0 AUDPC (−13.5%)</text>')

    elems.append("</svg>")
    (BRAND_DIR / out_name).write_text("\n".join(elems), encoding="utf-8")


def _load_real_lwd_bars() -> list[float]:
    raw = json.loads((ROOT / "docs" / "figures" / "failure_timelines_summary.json").read_text(encoding="utf-8"))
    # Real 75-day hourly sensor LWD totals from INRAE Bordeaux 2021 (Figure 2B)
    return [float(x) for x in raw["bordeaux_2021"]["sensor_lwd_h"]]


def _build_linkedin_banner(lang: str, show_safezone: bool = False, default_variant: str = "c") -> None:
    W, H = 1584, 396
    lwd_bars = _load_real_lwd_bars()
    icon_inner = {"a": _icon_a_inner(), "b": _icon_b_inner(), "c": _icon_c_inner()}[default_variant]

    if lang == "pt":
        headline = "Agrometeorologia e modelagem de doenças de plantas"
        subline = "Regras de pulverização testadas com dados de sensores reais"
        out_name = "banner-linkedin-pt.svg"
    else:
        headline = "Agrometeorology and plant disease modelling"
        subline = "Spray rules tested against real field sensor data"
        out_name = "banner-linkedin-en.svg"

    if show_safezone:
        out_name = "banner-linkedin-safezone-preview.svg"

    # Text strictly inside 36% .. 90% width (x = 570 .. 1425), vertically centered
    tx = 576
    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="font-family:{FONT};background:{BG}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        # Top subtle accent bar
        f'<rect x="0" y="0" width="{int(W*0.65)}" height="6" fill="{TEAL}"/>',
        f'<rect x="{int(W*0.65)}" y="0" width="{W - int(W*0.65)}" height="6" fill="{ORANGE}"/>',
    ]

    # Real daily sensor LWD background bars along bottom-right (subtle, below subtitle for high contrast)
    bar_x0 = 560.0
    bar_w_total = W - bar_x0 - 44.0
    step = bar_w_total / len(lwd_bars)
    bw = max(step * 0.56, 4.0)
    max_bar_h = 104.0
    for idx, val in enumerate(lwd_bars):
        bh = (min(val, 24.0) / 24.0) * max_bar_h
        bx = bar_x0 + idx * step
        by = H - bh
        elems.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" fill="{TEAL}" fill-opacity="0.12"/>')

    # Very subtle watermark leaf in far upper-right corner (outside text zone)
    elems.append(f'<g transform="translate(1415 24) scale(1.15)" opacity="0.06">{icon_inner}</g>')

    # Small crisp brand mark + lowercase vitirule tag inside safe zone (x=576)
    elems.append(f'<g transform="translate({tx} 86) scale(0.31)">{icon_inner}</g>')
    elems.append(f'<text x="{tx+48}" y="116" font-size="24" font-weight="700" letter-spacing="-0.6" fill="{TEAL}">vitirule</text>')

    # Main high-contrast typography (centered vertically, strictly inside 36%..88%)
    head_size = 31.5 if lang == "pt" else 34
    elems.append(f'<text x="{tx}" y="186" font-size="{head_size}" font-weight="800" letter-spacing="-0.5" fill="{DARK}">{headline}</text>')
    elems.append(f'<line x1="{tx}" y1="209" x2="{tx+78}" y2="209" stroke="{ORANGE}" stroke-width="4" stroke-linecap="round"/>')
    elems.append(f'<text x="{tx}" y="250" font-size="22.5" font-weight="500" fill="{MUTED}">{subline}</text>')

    if show_safezone:
        # Gray circle simulating LinkedIn desktop profile photo (bottom-left ~400px width, lower half)
        elems.append('<rect x="0" y="198" width="400" height="198" fill="#94a3b8" fill-opacity="0.18" stroke="#64748b" stroke-dasharray="6,4"/>')
        elems.append('<circle cx="215" cy="340" r="118" fill="#64748b" fill-opacity="0.55" stroke="#334155" stroke-width="2.5"/>')
        elems.append('<text x="215" y="328" text-anchor="middle" font-size="16" font-weight="700" fill="#ffffff">Profile Photo</text>')
        elems.append('<text x="215" y="350" text-anchor="middle" font-size="12" fill="#f1f5f9">(desktop overlap)</text>')
        # Safe text band markers (35% and 90% width)
        x35, x90 = int(W * 0.35), int(W * 0.90)
        elems.append(f'<line x1="{x35}" y1="0" x2="{x35}" y2="{H}" stroke="#0284c7" stroke-width="1.8" stroke-dasharray="6,4"/>')
        elems.append(f'<line x1="{x90}" y1="0" x2="{x90}" y2="{H}" stroke="#0284c7" stroke-width="1.8" stroke-dasharray="6,4"/>')
        elems.append(f'<text x="{x35+8}" y="28" font-size="13" font-weight="700" fill="#0284c7">35% safe start</text>')
        elems.append(f'<text x="{x90-8}" y="28" text-anchor="end" font-size="13" font-weight="700" fill="#0284c7">90% safe end</text>')

    elems.append("</svg>")
    (BRAND_DIR / out_name).write_text("\n".join(elems), encoding="utf-8")


def main(default_variant: str = "a") -> int:
    build_icons_and_logos(default_variant=default_variant)
    _build_social_svg(1280, 640, "vitirule-social.svg", default_variant=default_variant)
    _build_social_svg(1200, 627, "vitirule-card.svg", default_variant=default_variant)
    _build_linkedin_banner("pt", show_safezone=False, default_variant=default_variant)
    _build_linkedin_banner("en", show_safezone=False, default_variant=default_variant)
    _build_linkedin_banner("en", show_safezone=True, default_variant=default_variant)
    print(f"Generated brand SVGs in {BRAND_DIR} (default icon variant: {default_variant.upper()})")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=("a", "b", "c"), default="a", help="Default icon variant for logo/social/banners")
    args = p.parse_args()
    raise SystemExit(main(default_variant=args.variant))
