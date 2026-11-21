"""Figure for the README: leaf wetness error depends more on the weather source than on the formula.

Values are the daily MAE (h/day) from the LWD validation table in the README (Section 1),
produced by `lwd_sensor_validation.py` against INRAE AgroClim and Politecnico di Torino sensors.

Usage:
    python scripts/make_lwd_source_figure.py
Writes docs/figures/fig0_lwd_source_vs_formula.svg
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# estimator: (station MAE, Open-Meteo MAE), h/day, April-September
DATA = {
    "INRAE AgroClim\n4 French stations, 52.7k h": {
        "rh90_hysteresis": (2.61, 4.07),
        "dpd_hysteresis": (2.76, 4.24),
        "rh85": (3.26, 4.30),
        "cart_kim2002": (3.25, 3.82),
    },
    "Politecnico di Torino\n6 Italian stations, 23.7k h": {
        "rh85": (2.59, 4.05),
        "dpd_hysteresis": (2.79, 4.13),
        "rh90_hysteresis": (2.85, 4.06),
        "cart_kim2002": (2.95, 4.28),
    },
}

STATION = "#0f766e"
REANALYSIS = "#c2410c"
INK = "#0f172a"
MUTED = "#64748b"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})

fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.9), sharex=True)
for ax, (network, rows) in zip(axes, DATA.items()):
    names = list(rows)
    for i, name in enumerate(names):
        st, om = rows[name]
        y = len(names) - 1 - i
        ax.plot([st, om], [y, y], color="#cbd5e1", lw=3, zorder=1)
        ax.scatter(st, y, s=70, color=STATION, zorder=2)
        ax.scatter(om, y, s=70, color=REANALYSIS, zorder=2)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(list(reversed(names)), fontfamily="DejaVu Sans Mono", fontsize=9)
    ax.set_title(network, fontsize=10.5, color=INK, loc="left")
    ax.set_xlim(2.2, 4.6)
    ax.set_ylim(-0.6, len(names) - 0.4)
    ax.grid(axis="x", color="#e2e8f0", lw=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Daily leaf wetness error, MAE (h/day)", color=MUTED)

axes[0].scatter([], [], s=70, color=STATION, label="Weather station input")
axes[0].scatter([], [], s=70, color=REANALYSIS, label="Open-Meteo reanalysis input")
fig.legend(loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.02))
fig.suptitle(
    "The weather source moves the error more than the wetness formula",
    fontsize=12.5, fontweight="bold", color=INK, x=0.02, ha="left",
)
fig.tight_layout(rect=(0, 0.07, 1, 0.95))

out = Path(__file__).resolve().parents[1] / "docs" / "figures" / "fig0_lwd_source_vs_formula.svg"
fig.savefig(out, format="svg", facecolor="white")
print(f"wrote {out}")
