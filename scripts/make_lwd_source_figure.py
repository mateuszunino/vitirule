"""Figure for the README: leaf wetness error depends more on the weather source than on the formula.

Values are the daily MAE (h/day) from the clean v1.0.2 LWD validation sample
(`data/v2_v102_errata_audit.json`), produced against INRAE AgroClim (8 clean
station-years, 34,880 h) and Politecnico di Torino (6 clean sites, 23,735 h).

Pure Python standard-library SVG renderer (zero external dependencies).

Usage:
    python scripts/make_lwd_source_figure.py
Writes docs/figures/fig0_lwd_source_vs_formula.svg
"""
from __future__ import annotations

import html
from pathlib import Path

# estimator: (station MAE, Open-Meteo MAE), h/day, April-September (clean v1.0.2 sample)
DATA = [
    (
        "INRAE AgroClim",
        "3 French stations (8 station-years, 34.9k h)",
        [
            ("rh90_hysteresis", 2.65, 3.94),
            ("dpd_hysteresis", 2.85, 4.16),
            ("rh85", 3.37, 4.24),
            ("cart_kim2002", 3.29, 3.61),
        ],
    ),
    (
        "Politecnico di Torino",
        "6 Italian stations (23.7k h)",
        [
            ("rh85", 2.59, 4.05),
            ("dpd_hysteresis", 2.79, 4.13),
            ("rh90_hysteresis", 2.85, 4.06),
            ("cart_kim2002", 2.95, 4.28),
        ],
    ),
]

STATION = "#0f766e"
REANALYSIS = "#c2410c"
INK = "#0f172a"
MUTED = "#64748b"


def build_svg() -> str:
    W, H = 920, 365
    xmin, xmax = 2.2, 4.6
    pw, ph = 295, 190
    panel_xs = [155, 595]
    top_y = 84

    def sx(px: float, v: float) -> float:
        return px + (v - xmin) / (xmax - xmin) * pw

    els = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        '<style>',
        '  text { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; }',
        '  .mono { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 11px; fill: #1e293b; }',
        '</style>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="24" y="30" font-size="16" font-weight="700" fill="{INK}">The weather source moves the error more than the wetness formula</text>',
    ]

    for (title, subtitle, rows), px in zip(DATA, panel_xs):
        els.append(f'<text x="{px}" y="58" font-size="12.5" font-weight="700" fill="{INK}">{html.escape(title)}</text>')
        els.append(f'<text x="{px}" y="74" font-size="10.5" fill="{MUTED}">{html.escape(subtitle)}</text>')

        # Grid lines and x-axis ticks
        for tick in (2.5, 3.0, 3.5, 4.0, 4.5):
            gx = sx(px, tick)
            els.append(f'<line x1="{gx:.1f}" y1="{top_y}" x2="{gx:.1f}" y2="{top_y + ph}" stroke="#e2e8f0" stroke-width="1"/>')
            els.append(f'<text x="{gx:.1f}" y="{top_y + ph + 16}" text-anchor="middle" font-size="10" fill="{MUTED}">{tick:.1f}</text>')

        # Bottom axis spine
        els.append(f'<line x1="{px}" y1="{top_y + ph}" x2="{px + pw}" y2="{top_y + ph}" stroke="#94a3b8" stroke-width="1"/>')
        els.append(f'<text x="{px + pw / 2:.1f}" y="{top_y + ph + 36}" text-anchor="middle" font-size="11" fill="{MUTED}">Daily leaf wetness error, MAE (h/day)</text>')

        # Dumbbell rows
        step = ph / len(rows)
        for i, (name, st, om) in enumerate(rows):
            cy = top_y + (i + 0.5) * step
            x_st = sx(px, st)
            x_om = sx(px, om)
            els.append(f'<text x="{px - 10}" y="{cy + 4:.1f}" text-anchor="end" class="mono">{html.escape(name)}</text>')
            els.append(f'<line x1="{x_st:.1f}" y1="{cy:.1f}" x2="{x_om:.1f}" y2="{cy:.1f}" stroke="#cbd5e1" stroke-width="3.5" stroke-linecap="round"/>')
            els.append(f'<circle cx="{x_st:.1f}" cy="{cy:.1f}" r="5.5" fill="{STATION}"/>')
            els.append(f'<circle cx="{x_om:.1f}" cy="{cy:.1f}" r="5.5" fill="{REANALYSIS}"/>')
            els.append(f'<text x="{x_st - 9:.1f}" y="{cy + 3.5:.1f}" text-anchor="end" font-size="9.5" font-weight="600" fill="{STATION}">{st:.2f}</text>')
            els.append(f'<text x="{x_om + 9:.1f}" y="{cy + 3.5:.1f}" text-anchor="start" font-size="9.5" font-weight="600" fill="{REANALYSIS}">{om:.2f}</text>')

    # Centered bottom legend
    ly = H - 20
    els.append(f'<circle cx="290" cy="{ly - 4}" r="5.5" fill="{STATION}"/>')
    els.append(f'<text x="302" y="{ly}" font-size="11" fill="{INK}">Weather station input</text>')
    els.append(f'<circle cx="485" cy="{ly - 4}" r="5.5" fill="{REANALYSIS}"/>')
    els.append(f'<text x="497" y="{ly}" font-size="11" fill="{INK}">Open-Meteo reanalysis input</text>')

    els.append("</svg>")
    return "\n".join(els)


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "docs" / "figures" / "fig0_lwd_source_vs_formula.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_svg(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
