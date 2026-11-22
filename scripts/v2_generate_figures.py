#!/usr/bin/env python3
"""
scripts/v2_generate_figures.py
==============================
Gera figuras vetoriais SVG reproduziveis (biblioteca padrao Python pura, zero
dependencias externas) e tabelas CSV do vitirule v2 a partir dos JSONs de
resultado locais (`data/v2_phase3_exploratory_results.json` e
`data/v2_phase4_brazil_results.json`).

Modos de execucao:
- Padrao: gera todas as figuras da v2 em `docs/v2/figures/` e tabelas CSV em
  `docs/v2/tables/`. Qualquer figura contendo dados derivados do Politecnico di
  Torino inclui nota obrigatoria `CC BY-NC 4.0 (DOI 10.17632/sd4b8vpvyb.1)`.
- `--public-only`: usado pelo GitHub Actions CI (`workflow_dispatch`); gera
  exclusivamente figuras e tabelas derivadas de dados publicos (INMET SC + IBGE
  PAM + Open-Meteo + NASA POWER), sem tocar em nada derivado do Politecnico.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Paleta Okabe-Ito (segura para daltonismo)
COLORS = {
    "station_no_sensor": "#0072B2",
    "historical_forecast": "#E69F00",
    "era5_combined": "#009E73",
    "era5_land": "#009E73",
    "nasa_power": "#D55E00",
}

SOURCE_LABELS = {
    "station_no_sensor": "Local station (no LWD sensor)",
    "historical_forecast": "Historical Forecast",
    "era5_combined": "ERA5 combined (0.1° T/RH, 0.25° precip)",
    "era5_land": "ERA5 combined (0.1° T/RH, 0.25° precip)",
    "nasa_power": "NASA POWER (MERRA-2, UTC)",
}


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _marker_svg(kind: str, cx: float, cy: float, color: str, r: float = 5.5, hollow: bool = False) -> str:
    fill = "white" if hollow else color
    stroke = color if hollow else "#1a1a1a"
    sw = 2.0 if hollow else 0.8
    if kind == "station_no_sensor":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    if kind == "historical_forecast":
        return f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    if kind in ("era5_combined", "era5_land"):
        pts = f"{cx:.1f},{cy - r * 1.15:.1f} {cx - r * 1.1:.1f},{cy + r:.1f} {cx + r * 1.1:.1f},{cy + r:.1f}"
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    # diamond (nasa_power)
    pts = f"{cx:.1f},{cy - r * 1.15:.1f} {cx + r * 1.15:.1f},{cy:.1f} {cx:.1f},{cy + r * 1.15:.1f} {cx - r * 1.15:.1f},{cy:.1f}"
    return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def _svg_header(w: int, h: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        '<style>',
        '  text { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; fill: #1f2937; }',
        '  .title { font-size: 16px; font-weight: 700; }',
        '  .panel-title { font-size: 13px; font-weight: 700; }',
        '  .axis-label { font-size: 11px; fill: #374151; }',
        '  .tick { font-size: 10px; fill: #4b5563; }',
        '  .ann { font-size: 9.5px; font-weight: 600; }',
        '  .note { font-size: 10px; fill: #4b5563; font-style: italic; }',
        '  .legend { font-size: 11px; }',
        '</style>',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>',
    ]


def plot_fig1_europe_miss_far(p3: dict[str, Any], out_dir: Path) -> Path:
    """INRAE exploratory (no Politecnico): Missed alerts vs FAR across 4 rules."""
    prim = p3["primary_analysis_2022_2025"]["inrae_exploratory"]["by_rule"]
    W, H = 980, 745
    els = _svg_header(W, H)
    els.append(f'<text x="{W / 2}" y="28" text-anchor="middle" class="title">European Exploratory Evaluation (INRAE, 4 stations, 2022–2025, rh90_rain, daily_min)</text>')

    sources = ["station_no_sensor", "historical_forecast", "era5_land", "nasa_power"]
    # Legend row
    lx = 60
    for src in sources:
        els.append(_marker_svg(src, lx, 52, COLORS[src], r=5.2))
        els.append(f'<text x="{lx + 11}" y="56" class="legend">{_esc(SOURCE_LABELS[src])}</text>')
        lx += 230 if src != "era5_land" else 275

    panels = [
        ("rule_3_10", "A. Rule 3-10 (n = 130 ref. events)", 72, 92, False),
        ("goidanich", "B. Goidànich (n = 119 ref. cycles)", 530, 92, False),
        ("mills_revised", "C. Revised Mills (n = 249 ref. events)", 72, 408, True),
        ("tomcast_self", "D. TOM-CAST self_reset (n = 47 ref. sprays)", 530, 408, True),
    ]
    pw, ph = 405, 250
    x_max, y_max = 88.0, 78.0

    # Explicit collision-free label offsets (dx, dy, anchor, draw_leader)
    label_pos: dict[tuple[str, str], tuple[float, float, str, bool]] = {
        ("rule_3_10", "historical_forecast"): (-12, 16, "end", True),
        ("rule_3_10", "nasa_power"): (-12, -16, "end", True),
        ("rule_3_10", "era5_land"): (10, 4, "start", False),
        ("goidanich", "historical_forecast"): (-12, -10, "end", True),
        ("goidanich", "nasa_power"): (12, -14, "start", True),
        ("goidanich", "era5_land"): (10, 12, "start", False),
        ("mills_revised", "station_no_sensor"): (12, -16, "start", True),
        ("mills_revised", "historical_forecast"): (10, -10, "start", False),
        ("mills_revised", "era5_land"): (10, 12, "start", False),
        ("mills_revised", "nasa_power"): (10, 4, "start", False),
        ("tomcast_self", "station_no_sensor"): (-12, -4, "end", True),
        ("tomcast_self", "historical_forecast"): (12, -10, "start", True),
        ("tomcast_self", "era5_land"): (-10, 14, "end", False),
        ("tomcast_self", "nasa_power"): (-10, -10, "end", False),
    }

    for rkey, title, px, py, include_station_no_sensor in panels:
        els.append(f'<text x="{px}" y="{py - 10}" class="panel-title">{_esc(title)}</text>')
        # Usability box (FAR <= 30, Miss <= 20)
        ux = px
        uy = py + ph - (20.0 / y_max) * ph
        uw = (30.0 / x_max) * pw
        uh = (20.0 / y_max) * ph
        els.append(f'<rect x="{ux:.1f}" y="{uy:.1f}" width="{uw:.1f}" height="{uh:.1f}" fill="#e6f4ea" stroke="#2e7d32" stroke-width="1.2"/>')
        els.append(f'<text x="{ux + 5:.1f}" y="{uy + 14:.1f}" style="font-size:9px;fill:#1b5e20;font-weight:600;">Usability target</text>')
        els.append(f'<text x="{ux + 5:.1f}" y="{uy + 26:.1f}" style="font-size:8.5px;fill:#1b5e20;">Miss ≤ 20%, FAR ≤ 30%</text>')

        if not include_station_no_sensor:
            els.append(
                f'<text x="{px + pw - 6:.1f}" y="{py + 15:.1f}" text-anchor="end" '
                f'style="font-size:8.5px;fill:#4b5563;font-style:italic;">'
                f'Station without LWD sensor not shown: input identical to reference.</text>'
            )

        # Grid & ticks
        for gx in (0, 20, 40, 60, 80):
            x = px + (gx / x_max) * pw
            els.append(f'<line x1="{x:.1f}" y1="{py}" x2="{x:.1f}" y2="{py + ph}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
            els.append(f'<text x="{x:.1f}" y="{py + ph + 15}" text-anchor="middle" class="tick">{gx}%</text>')
        for gy in (0, 20, 40, 60):
            y = py + ph - (gy / y_max) * ph
            els.append(f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
            els.append(f'<text x="{px - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy}%</text>')
        # Axes
        els.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')
        els.append(f'<line x1="{px}" y1="{py + ph}" x2="{px + pw}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')

        rmap = prim[rkey]
        panel_sources = sources if include_station_no_sensor else [s for s in sources if s != "station_no_sensor"]
        for src in panel_sources:
            pt = rmap[src]["point"]
            ci = (rmap[src].get("ci95_station_bootstrap") or {}).get("missed_rate")
            miss = (pt["missed_rate"] or 0.0) * 100.0
            far = (pt["far"] or 0.0) * 100.0
            cx = px + (far / x_max) * pw
            cy = py + ph - (miss / y_max) * ph
            if ci is not None:
                y_lo = py + ph - (min(y_max, ci[1] * 100.0) / y_max) * ph
                y_hi = py + ph - (max(0.0, ci[0] * 100.0) / y_max) * ph
                els.append(f'<line x1="{cx:.1f}" y1="{y_lo:.1f}" x2="{cx:.1f}" y2="{y_hi:.1f}" stroke="{COLORS[src]}" stroke-width="1.5"/>')
                els.append(f'<line x1="{cx - 4:.1f}" y1="{y_lo:.1f}" x2="{cx + 4:.1f}" y2="{y_lo:.1f}" stroke="{COLORS[src]}" stroke-width="1.4"/>')
                els.append(f'<line x1="{cx - 4:.1f}" y1="{y_hi:.1f}" x2="{cx + 4:.1f}" y2="{y_hi:.1f}" stroke="{COLORS[src]}" stroke-width="1.4"/>')
            els.append(_marker_svg(src, cx, cy, COLORS[src], r=5.5))
            dx, dy, anchor, draw_leader = label_pos.get((rkey, src), (10, -8, "start", False))
            lx_t, ly_t = cx + dx, cy + dy
            if draw_leader:
                els.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx_t:.1f}" y2="{ly_t - 2:.1f}" stroke="{COLORS[src]}" stroke-width="0.7" opacity="0.65"/>')
            els.append(f'<text x="{lx_t:.1f}" y="{ly_t:.1f}" text-anchor="{anchor}" class="ann" style="fill:{COLORS[src]};">F1={pt["f1"]:.2f}</text>')

    els.append(f'<text x="{W / 2}" y="696" text-anchor="middle" class="axis-label">False alarm ratio, FAR (%)</text>')
    els.append(f'<text x="20" y="388" text-anchor="middle" transform="rotate(-90 20 388)" class="axis-label">Missed Alerts (%) with 95% station-bootstrap CI</text>')
    els.append(f'<text x="{W / 2}" y="726" text-anchor="middle" class="note">Exploratory set (4 v1 INRAE stations); European confirmatory run (v2-confirmatory) pending INRAE portal recovery from HTTP 503.</text>')
    els.append('</svg>')

    out = out_dir / "fig1_europe_exploratory_miss_far.svg"
    out.write_text("\n".join(els), encoding="utf-8")
    return out


def plot_fig2_cost_loss_and_tomcast(p3: dict[str, Any], out_dir: Path) -> Path:
    """2-panel: (A) INRAE daily cost-loss V(0.10); (B) TOM-CAST reference_reset vs self_reset (includes Politecnico CC BY-NC 4.0)."""
    prim_inrae = p3["primary_analysis_2022_2025"]["inrae_exploratory"]["by_rule"]
    prim_pol = p3["primary_analysis_2022_2025"]["polito_exploratory_descriptive_only"]["by_rule"]
    W, H = 1040, 470
    els = _svg_header(W, H)
    els.append(f'<text x="{W / 2}" y="26" text-anchor="middle" class="title">Economic Value and TOM-CAST Error Propagation (European Exploratory Set, 2022–2025)</text>')

    sources = ["station_no_sensor", "historical_forecast", "era5_land", "nasa_power"]
    lx = 65
    for src in sources:
        els.append(_marker_svg(src, lx, 50, COLORS[src], r=5.0))
        els.append(f'<text x="{lx + 10}" y="54" class="legend">{_esc(SOURCE_LABELS[src])}</text>')
        lx += 235 if src != "era5_land" else 285

    # Panel A: grouped bar chart V(0.10), omitting station_no_sensor on 3-10 and Goidanich
    px, py, pw, ph = 70, 92, 420, 290
    y_min, y_max = -0.60, 0.85
    els.append(f'<text x="{px}" y="{py - 10}" class="panel-title">A. Daily Cost-Loss Value V(C/L = 0.10), INRAE Exploratory</text>')

    def _y_a(v: float) -> float:
        return py + ph - ((v - y_min) / (y_max - y_min)) * ph

    for gy in (-0.5, 0.0, 0.5):
        y = _y_a(gy)
        st = "#111827" if gy == 0.0 else "#e5e7eb"
        sw = 1.2 if gy == 0.0 else 0.9
        dash = "" if gy == 0.0 else ' stroke-dasharray="3,3"'
        els.append(f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="{st}" stroke-width="{sw}"{dash}/>')
        els.append(f'<text x="{px - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy:+.1f}</text>')
    els.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')

    rules = [
        ("rule_3_10", "Rule 3-10", False),
        ("goidanich", "Goidànich", False),
        ("mills_revised", "Revised Mills", True),
        ("tomcast_self", "TOM-CAST", True),
    ]
    grp_w = pw / len(rules)
    bar_w = 18.0
    y0 = _y_a(0.0)
    for gi, (rk, lbl, include_station) in enumerate(rules):
        gx_center = px + (gi + 0.5) * grp_w
        els.append(f'<text x="{gx_center:.1f}" y="{py + ph + 18}" text-anchor="middle" class="tick">{_esc(lbl)}</text>')
        rule_sources = sources if include_station else [s for s in sources if s != "station_no_sensor"]
        n_s = len(rule_sources)
        for si, src in enumerate(rule_sources):
            val = prim_inrae[rk][src]["point"]["cost_loss"]["by_ratio"]["0.10"]["relative_value"]
            bx_bar = gx_center + (si - (n_s - 1) / 2.0) * (bar_w + 2.0) - bar_w / 2.0
            yv = _y_a(val)
            top = min(y0, yv)
            bh_bar = abs(yv - y0)
            els.append(f'<rect x="{bx_bar:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{max(1.0, bh_bar):.1f}" fill="{COLORS[src]}" stroke="#1f2937" stroke-width="0.4"/>')

    els.append(f'<text x="{px + 6}" y="{py + 14}" style="font-size:8.3px;fill:#4b5563;font-style:italic;">Station without LWD sensor not shown for 3-10 and Goidànich: input identical to reference.</text>')
    els.append(f'<text x="{px + 8}" y="{py + ph - 8}" style="font-size:9px;fill:#991b1b;">V &lt; 0: worse than fixed always/never spraying</text>')

    # Panel B: TOM-CAST reference_reset DSV error vs self_reset spray multiplier
    bx, by, bw, bh = 570, 92, 435, 290
    els.append(f'<text x="{bx}" y="{by - 10}" class="panel-title">B. TOM-CAST Input Fidelity vs. Operational Propagation</text>')
    xmin_b, xmax_b = -13.0, 46.0
    ymin_b, ymax_b = 0.0, 4.6

    def _x_b(v: float) -> float:
        return bx + ((v - xmin_b) / (xmax_b - xmin_b)) * bw

    def _y_b(v: float) -> float:
        return by + bh - ((v - ymin_b) / (ymax_b - ymin_b)) * bh

    for gx in (-10, 0, 10, 20, 30, 40):
        x = _x_b(gx)
        st = "#6b7280" if gx == 0 else "#e5e7eb"
        els.append(f'<line x1="{x:.1f}" y1="{by}" x2="{x:.1f}" y2="{by + bh}" stroke="{st}" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{x:.1f}" y="{by + bh + 16}" text-anchor="middle" class="tick">{gx:+d}</text>')
    for gy in (0, 1, 2, 3, 4):
        y = _y_b(gy)
        st = "#6b7280" if gy == 1 else "#e5e7eb"
        els.append(f'<line x1="{bx}" y1="{y:.1f}" x2="{bx + bw}" y2="{y:.1f}" stroke="{st}" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{bx - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy:.0f}×</text>')
    els.append(f'<line x1="{bx}" y1="{by}" x2="{bx}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')
    els.append(f'<line x1="{bx}" y1="{by + bh}" x2="{bx + bw}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')

    for src in sources:
        rr = prim_inrae["tomcast_ref_reset"][src]
        sr = prim_inrae["tomcast_self"][src]["point"]
        mult = sr["n_cand"] / sr["n_ref"]
        dsv = rr["mean_dsv_error_at_ref"]
        cx, cy = _x_b(dsv), _y_b(mult)
        els.append(_marker_svg(src, cx, cy, COLORS[src], r=6.2, hollow=False))
        if src == "nasa_power":
            dx, dy, anch = -10, 4, "end"
        elif src == "station_no_sensor":
            dx, dy, anch = 10, 14, "start"
        elif src == "historical_forecast":
            dx, dy, anch = 10, -10, "start"
        else:
            dx, dy, anch = 10, -8, "start"
        els.append(f'<text x="{cx + dx:.1f}" y="{cy + dy:.1f}" text-anchor="{anch}" class="ann" style="fill:{COLORS[src]};">INRAE ({dsv:+.1f}, {mult:.2f}×)</text>')

        rr_p = prim_pol["tomcast_ref_reset"][src]
        sr_p = prim_pol["tomcast_self"][src]["point"]
        mult_p = sr_p["n_cand"] / sr_p["n_ref"]
        dsv_p = rr_p["mean_dsv_error_at_ref"]
        cxp, cyp = _x_b(dsv_p), _y_b(mult_p)
        els.append(_marker_svg(src, cxp, cyp, COLORS[src], r=5.5, hollow=True))
        p_dy = 14 if src == "historical_forecast" else 4
        els.append(f'<text x="{cxp + 8:.1f}" y="{cyp + p_dy:.1f}" style="font-size:8.5px;fill:{COLORS[src]};">PoliTO</text>')

    els.append(f'<text x="{bx + bw / 2}" y="{by + bh + 34}" text-anchor="middle" class="axis-label">reference_reset Mean DSV Error at Reference Spray Date (DSV)</text>')
    els.append(f'<text x="{bx - 40}" y="{by + bh / 2}" text-anchor="middle" transform="rotate(-90 {bx - 40} {by + bh / 2})" class="axis-label">self_reset Spray Multiplier</text>')
    els.append(f'<text x="{bx + 8}" y="{by + 16}" style="font-size:9px;fill:#374151;">Filled: INRAE (4 st.) | Open: Politecnico (2 st., descriptive)</text>')
    els.append(f'<text x="{W / 2}" y="454" text-anchor="middle" class="note">Politecnico di Torino values (open symbols in Panel B) derive from CC BY-NC 4.0 data (DOI 10.17632/sd4b8vpvyb.1), descriptive only without CIs; no raw data redistributed.</text>')
    els.append('</svg>')

    out = out_dir / "fig2_europe_cost_loss_and_tomcast.svg"
    out.write_text("\n".join(els), encoding="utf-8")
    return out


def plot_fig3_previous_runs(p3: dict[str, Any], out_dir: Path) -> Path:
    """INRAE exploratory 2024-2025: Historical Forecast vs Previous Runs lead days 1-3."""
    sec_b = p3["secondary_analyses"]["secondary_B_previous_runs_2024_2025_inrae"]["by_rule"]
    W, H = 980, 425
    els = _svg_header(W, H)
    els.append(f'<text x="{W / 2}" y="26" text-anchor="middle" class="title">Quasi-Analysis vs. 1–3 Day Forecast Lead Time (INRAE Exploratory, 2024–2025)</text>')

    leads = ["historical_forecast", "previous_day1", "previous_day2", "previous_day3"]
    lead_labels = ["Hist. Forecast", "Lead 1 d", "Lead 2 d", "Lead 3 d"]
    rules = [
        ("rule_3_10", "Rule 3-10", "#0072B2", "station_no_sensor"),
        ("goidanich", "Goidànich", "#009E73", "era5_combined"),
        ("mills_revised", "Revised Mills", "#D55E00", "nasa_power"),
    ]
    lx = 300
    for _, lbl, col, mk in rules:
        els.append(_marker_svg(mk, lx, 50, col, r=5.0))
        els.append(f'<text x="{lx + 11}" y="54" class="legend">{_esc(lbl)}</text>')
        lx += 145

    # Panel A: Missed Alerts (%)
    px, py, pw, ph = 70, 90, 395, 265
    els.append(f'<text x="{px}" y="{py - 10}" class="panel-title">A. Missed Alerts Rise with Forecast Lead Time</text>')
    ymin_a, ymax_a = 15.0, 46.0
    for gy in (20, 25, 30, 35, 40, 45):
        y = py + ph - ((gy - ymin_a) / (ymax_a - ymin_a)) * ph
        st = "#2e7d32" if gy == 20 else "#e5e7eb"
        els.append(f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="{st}" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{px - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy}%</text>')
    els.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')
    els.append(f'<line x1="{px}" y1="{py + ph}" x2="{px + pw}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')

    xs = [px + 38 + i * ((pw - 86) / 3.0) for i in range(4)]
    for x, lbl in zip(xs, lead_labels):
        els.append(f'<text x="{x:.1f}" y="{py + ph + 18}" text-anchor="middle" class="tick">{_esc(lbl)}</text>')

    # Collision-free offsets (dx, dy, anchor, draw_leader) for Panel A
    offsets_a: dict[tuple[str, int], tuple[float, float, str, bool]] = {
        ("rule_3_10", 0): (0, 16, "middle", False),
        ("rule_3_10", 1): (0, 16, "middle", False),
        ("rule_3_10", 2): (0, 16, "middle", False),
        ("rule_3_10", 3): (0, 17, "middle", False),
        ("goidanich", 0): (-8, 15, "end", True),
        ("goidanich", 1): (0, -11, "middle", False),
        ("goidanich", 2): (0, -11, "middle", False),
        ("goidanich", 3): (-8, -11, "end", False),
        ("mills_revised", 0): (0, -11, "middle", False),
        ("mills_revised", 1): (-14, 2, "end", True),
        ("mills_revised", 2): (0, 16, "middle", False),
        ("mills_revised", 3): (12, 3, "start", True),
    }

    for rkey, _, col, mk in rules:
        pts = []
        for idx_l, (x, lk) in enumerate(zip(xs, leads)):
            m = sec_b[rkey][lk]["point"]["missed_rate"] * 100.0
            y = py + ph - ((m - ymin_a) / (ymax_a - ymin_a)) * ph
            pts.append((idx_l, x, y, m))
        poly = " ".join(f"{x:.1f},{y:.1f}" for _, x, y, _ in pts)
        els.append(f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="2.2"/>')
        for idx_l, x, y, m in pts:
            els.append(_marker_svg(mk, x, y, col, r=5.0))
            dx, dy, anch, ldr = offsets_a[(rkey, idx_l)]
            lx_t, ly_t = x + dx, y + dy
            if ldr:
                els.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{lx_t:.1f}" y2="{ly_t - 3:.1f}" stroke="{col}" stroke-width="0.7" opacity="0.7"/>')
            els.append(f'<text x="{lx_t:.1f}" y="{ly_t:.1f}" text-anchor="{anch}" class="ann" style="fill:{col};">{m:.1f}%</text>')

    # Panel B: Daily Cost-Loss Value V(0.10)
    bx, by, bw, bh = 540, 90, 395, 265
    els.append(f'<text x="{bx}" y="{by - 10}" class="panel-title">B. Daily Cost-Loss Value V(C/L = 0.10)</text>')
    ymin_b, ymax_b = -0.15, 0.58
    for gy in (-0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        y = by + bh - ((gy - ymin_b) / (ymax_b - ymin_b)) * bh
        st = "#111827" if gy == 0.0 else "#e5e7eb"
        dash = "" if gy == 0.0 else ' stroke-dasharray="3,3"'
        els.append(f'<line x1="{bx}" y1="{y:.1f}" x2="{bx + bw}" y2="{y:.1f}" stroke="{st}"{dash}/>')
        els.append(f'<text x="{bx - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy:+.1f}</text>')
    els.append(f'<line x1="{bx}" y1="{by}" x2="{bx}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')
    els.append(f'<line x1="{bx}" y1="{by + bh}" x2="{bx + bw}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')

    xs2 = [bx + 38 + i * ((bw - 86) / 3.0) for i in range(4)]
    for x, lbl in zip(xs2, lead_labels):
        els.append(f'<text x="{x:.1f}" y="{by + bh + 18}" text-anchor="middle" class="tick">{_esc(lbl)}</text>')

    offsets_b: dict[tuple[str, int], tuple[float, float, str]] = {
        ("rule_3_10", 0): (0, -10, "middle"),
        ("rule_3_10", 1): (0, -10, "middle"),
        ("rule_3_10", 2): (0, 16, "middle"),
        ("rule_3_10", 3): (0, -10, "middle"),
        ("goidanich", 0): (0, 16, "middle"),
        ("goidanich", 1): (0, 16, "middle"),
        ("goidanich", 2): (0, -10, "middle"),
        ("goidanich", 3): (0, 16, "middle"),
        ("mills_revised", 0): (0, 16, "middle"),
        ("mills_revised", 1): (0, -10, "middle"),
        ("mills_revised", 2): (0, -10, "middle"),
        ("mills_revised", 3): (0, 16, "middle"),
    }

    for rkey, _, col, mk in rules:
        pts = []
        for idx_l, (x, lk) in enumerate(zip(xs2, leads)):
            v = sec_b[rkey][lk]["point"]["cost_loss"]["by_ratio"]["0.10"]["relative_value"]
            y = by + bh - ((v - ymin_b) / (ymax_b - ymin_b)) * bh
            pts.append((idx_l, x, y, v))
        poly = " ".join(f"{x:.1f},{y:.1f}" for _, x, y, _ in pts)
        els.append(f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="2.2"/>')
        for idx_l, x, y, v in pts:
            els.append(_marker_svg(mk, x, y, col, r=5.0))
            dx, dy, anch = offsets_b[(rkey, idx_l)]
            els.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anch}" class="ann" style="fill:{col};">{v:+.2f}</text>')

    els.append(f'<text x="{W / 2}" y="408" text-anchor="middle" class="note">INRAE exploratory stations (2024–2025) comparing Open-Meteo Historical Forecast against Open-Meteo Previous Runs (lead 1–3 days).</text>')
    els.append('</svg>')

    out = out_dir / "fig3_previous_runs_degradation.svg"
    out.write_text("\n".join(els), encoding="utf-8")
    return out


def plot_fig4_santa_catarina(p4: dict[str, Any], out_dir: Path) -> Path:
    """Public-data Brazil Phase 4 figure (CI-safe, zero Politecnico)."""
    res = p4["results"]
    diag = p4["exploratory_relief_and_convective_diagnosis"]["stations"]
    W, H = 1060, 470
    els = _svg_header(W, H)
    els.append(f'<text x="{W / 2}" y="26" text-anchor="middle" class="title">Santa Catarina Transfer Against INMET Automatic Stations (2022–2025, v2-freeze-br)</text>')

    sources = ["era5_combined", "historical_forecast", "nasa_power"]
    lx = 130
    for src in sources:
        els.append(_marker_svg(src, lx, 50, COLORS[src], r=5.0))
        els.append(f'<text x="{lx + 11}" y="54" class="legend">{_esc(SOURCE_LABELS[src])}</text>')
        lx += 315 if src == "era5_combined" else 235

    # Panel A: Grouped bar chart F1 across 4 rules
    px, py, pw, ph = 65, 92, 440, 290
    els.append(f'<text x="{px}" y="{py - 10}" class="panel-title">A. Agreement F1 vs. INMET (Mills Candidate Error; Others Divergence)</text>')
    for gy in (0.0, 0.2, 0.4, 0.6, 0.8):
        y = py + ph - (gy / 0.95) * ph
        els.append(f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{px - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy:.1f}</text>')
    els.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')
    els.append(f'<line x1="{px}" y1="{py + ph}" x2="{px + pw}" y2="{py + ph}" stroke="#374151" stroke-width="1.2"/>')

    rules = [
        ("mills_revised", "Revised Mills*", "7 st., cand. error"),
        ("rule_3_10", "Rule 3-10", "8 st., divergence"),
        ("goidanich", "Goidànich", "8 st., divergence"),
        ("tomcast", "TOM-CAST self", "10 st., divergence"),
    ]
    grp_w = pw / len(rules)
    bar_w = 24.0
    for gi, (rk, l1, l2) in enumerate(rules):
        gc = px + (gi + 0.5) * grp_w
        els.append(f'<text x="{gc:.1f}" y="{py + ph + 16}" text-anchor="middle" class="tick" style="font-weight:600;">{_esc(l1)}</text>')
        els.append(f'<text x="{gc:.1f}" y="{py + ph + 28}" text-anchor="middle" style="font-size:8.5px;fill:#6b7280;">{_esc(l2)}</text>')
        for si, src in enumerate(sources):
            val = res[rk][src]["point"]["f1"]
            bx_i = gc + (si - 1) * (bar_w + 3.0) - bar_w / 2.0
            bh_i = (val / 0.95) * ph
            els.append(f'<rect x="{bx_i:.1f}" y="{py + ph - bh_i:.1f}" width="{bar_w:.1f}" height="{bh_i:.1f}" fill="{COLORS[src]}" stroke="#1f2937" stroke-width="0.4"/>')
            els.append(f'<text x="{bx_i + bar_w / 2:.1f}" y="{py + ph - bh_i - 4:.1f}" text-anchor="middle" style="font-size:8.5px;fill:#1f2937;">{val:.2f}</text>')

    # Panel B: Exploratory Mills F1 vs Station Elevation — scatter points only (independent stations, no connecting lines)
    bx, by, bw, bh = 580, 92, 445, 290
    els.append(f'<text x="{bx}" y="{by - 10}" class="panel-title">B. Exploratory Relief Profile: Mills F1 vs. Station Elevation</text>')
    xmin_b, xmax_b = 400.0, 1500.0
    ymin_b, ymax_b = 0.30, 0.88

    def _x_b(v: float) -> float:
        return bx + ((v - xmin_b) / (xmax_b - xmin_b)) * bw

    def _y_b(v: float) -> float:
        return by + bh - ((v - ymin_b) / (ymax_b - ymin_b)) * bh

    for gx in (500, 700, 900, 1100, 1300, 1500):
        x = _x_b(gx)
        els.append(f'<line x1="{x:.1f}" y1="{by}" x2="{x:.1f}" y2="{by + bh}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{x:.1f}" y="{by + bh + 16}" text-anchor="middle" class="tick">{gx} m</text>')
    for gy in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        y = _y_b(gy)
        els.append(f'<line x1="{bx}" y1="{y:.1f}" x2="{bx + bw}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
        els.append(f'<text x="{bx - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{gy:.1f}</text>')
    els.append(f'<line x1="{bx}" y1="{by}" x2="{bx}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')
    els.append(f'<line x1="{bx}" y1="{by + bh}" x2="{bx + bw}" y2="{by + bh}" stroke="#374151" stroke-width="1.2"/>')

    mills_sts = sorted([s for s in diag if s["mills_f1_by_source"]["era5_combined"] is not None], key=lambda s: s["elevation_m"])
    # Subtle vertical range guide per station connecting its own 3 source points (not across stations)
    for s in mills_sts:
        x_st = _x_b(s["elevation_m"])
        vals_st = [s["mills_f1_by_source"][src] for src in sources]
        els.append(f'<line x1="{x_st:.1f}" y1="{_y_b(max(vals_st)):.1f}" x2="{x_st:.1f}" y2="{_y_b(min(vals_st)):.1f}" stroke="#d1d5db" stroke-width="1.1"/>')
    for src in sources:
        for s in mills_sts:
            els.append(_marker_svg(src, _x_b(s["elevation_m"]), _y_b(s["mills_f1_by_source"][src]), COLORS[src], r=5.4))

    display_names = {
        "ITUPORANGA": "Ituporanga",
        "CHAPECO": "Chapecó",
        "NOVO HORIZONTE": "Novo Horizonte",
        "CACADOR": "Caçador",
        "CAMPOS NOVOS": "Campos Novos",
        "CURITIBANOS": "Curitibanos",
        "SAO JOAQUIM": "São Joaquim",
    }
    # Explicit non-overlapping label targets: (label_elev_x, label_f1_y, anchor, anchor_from_min, draw_leader)
    label_layout = {
        "ITUPORANGA": (485.0, 0.685, "middle", False, False),
        "CHAPECO": (679.0, 0.590, "middle", True, False),
        "NOVO HORIZONTE": (895.0, 0.820, "end", False, True),
        "CAMPOS NOVOS": (1025.0, 0.835, "start", False, True),
        "CURITIBANOS": (1075.0, 0.745, "start", False, True),
        "CACADOR": (865.0, 0.375, "end", True, True),
        "SAO JOAQUIM": (1385.0, 0.715, "middle", False, False),
    }
    for s in mills_sts:
        nm = s["station_name"]
        disp = display_names.get(nm, nm.title())
        vals_st = [s["mills_f1_by_source"][src] for src in sources]
        lx_e, ly_f1, anch, from_min, draw_ldr = label_layout[nm]
        ref_y = min(vals_st) if from_min else max(vals_st)
        tx, ty = _x_b(lx_e), _y_b(ly_f1)
        if draw_ldr:
            els.append(f'<line x1="{_x_b(s["elevation_m"]):.1f}" y1="{_y_b(ref_y):.1f}" x2="{tx:.1f}" y2="{ty - 3:.1f}" stroke="#6b7280" stroke-width="0.75" stroke-dasharray="2,2"/>')
        els.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anch}" style="font-size:8.6px;fill:#1f2937;font-weight:600;">{_esc(disp)} ({s["elevation_m"]:.0f} m)</text>')

    els.append(f'<text x="{bx + bw / 2}" y="{by + bh + 34}" text-anchor="middle" class="axis-label">INMET Station Elevation (m a.s.l.)</text>')
    els.append(f'<text x="{W / 2}" y="454" text-anchor="middle" class="note">*Mills: divergence vs. INMET surrogate reference (missed 16.9% in Europe), candidate grid-error estimate pending v2-confirmatory. 3-10, Goidànich, TOM-CAST: divergence only. Panel B: exploratory.</text>')
    els.append('</svg>')

    out = out_dir / "fig4_santa_catarina_transfer.svg"
    out.write_text("\n".join(els), encoding="utf-8")
    return out


def export_public_brazil_tables(p4: dict[str, Any], tables_dir: Path) -> list[Path]:
    """Exporta tabelas CSV derivadas exclusivamente de dados publicos brasileiros (CI-safe)."""
    tables_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    t1 = tables_dir / "table_sc_24_stations_selection.csv"
    with t1.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "station_id", "station_name", "elevation_m", "ibge_pam_2025_producer",
            "maca_ha", "uva_ha", "tomate_ha",
            "apple_pass_of_4", "grapevine_pass_of_3", "tomato_pass_of_3",
            "qc_failure_criteria", "status",
        ])
        for s in p4["selection_table"]:
            p = s["ibge_pam_2025"]
            q = s["qc_pass_counts"]
            reasons = sorted({rs for rows in s["qc_details"].values() for r in rows if not r["passed"] for rs in r["reasons"]})
            w.writerow([
                s["station_id"], s["station_name"], s["elevation_m"],
                s["is_producing_municipality"],
                p["maca_ha"], p["uva_ha"], p["tomate_ha"],
                q["apple"], q["grapevine"], q["tomato"],
                ";".join(reasons), s["status"],
            ])
    written.append(t1)

    t2 = tables_dir / "table_sc_results_summary.csv"
    with t2.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "rule", "interpretation_label", "source", "n_stations", "n_station_seasons",
            "n_inmet", "n_grid", "unmatched_inmet_rate", "unmatched_ci95_lo", "unmatched_ci95_hi",
            "extra_ratio", "f1", "median_lag_days", "v_cl_005", "v_cl_010", "v_cl_020",
        ])
        for rule_name, rmap in p4["results"].items():
            interp = (
                "divergencia_inmet_candidata_erro_se_confirmatorio_europeu_repetir"
                if rule_name == "mills_revised"
                else "divergencia_apenas_nao_erro"
            )
            for src, r in rmap.items():
                pt = r["point"]
                ci = (r.get("ci95_station_bootstrap") or {}).get("missed_rate") or [None, None]
                cl = pt["cost_loss"]["by_ratio"]
                w.writerow([
                    rule_name, interp, src, r["n_stations"], r["n_station_seasons"],
                    pt["n_ref"], pt["n_cand"], pt["missed_rate"], ci[0], ci[1],
                    pt["far"], pt["f1"], pt["median_lag_days"],
                    cl["0.05"]["relative_value"], cl["0.10"]["relative_value"], cl["0.20"]["relative_value"],
                ])
    written.append(t2)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate vitirule v2 reproducible SVG figures and public CSV tables.")
    ap.add_argument("--public-only", action="store_true", help="Only process public Brazil INMET data (CI-safe, zero Politecnico).")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "v2" / "figures")
    ap.add_argument("--tables-dir", type=Path, default=ROOT / "docs" / "v2" / "tables")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    p4_path = ROOT / "data" / "v2_phase4_brazil_results.json"
    if p4_path.is_file():
        p4 = _load_json(p4_path)
        generated.append(plot_fig4_santa_catarina(p4, args.out_dir))
        generated.extend(export_public_brazil_tables(p4, args.tables_dir))

    if not args.public_only:
        p3_path = ROOT / "data" / "v2_phase3_exploratory_results.json"
        if p3_path.is_file():
            p3 = _load_json(p3_path)
            generated.append(plot_fig1_europe_miss_far(p3, args.out_dir))
            generated.append(plot_fig2_cost_loss_and_tomcast(p3, args.out_dir))
            generated.append(plot_fig3_previous_runs(p3, args.out_dir))

    for p in generated:
        print(f"Generated: {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
