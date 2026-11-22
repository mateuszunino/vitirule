"""
vitirule_v2.rules
=================
Quatro regras fitossanitarias publicadas implementadas como funcoes puras em
Python, usando apenas a biblioteca padrao para execucao direta no navegador via
Pyodide na Fase 5.
"""
from __future__ import annotations

from .apple_scab import MillsEvent, detect_mills_infections, mills_lookup
from .common import HourlyRecord, load_params, round_half_up
from .downy_mildew import (
    GoidanichCohort,
    Rule310Event,
    detect_rule_3_10,
    goidanich_daily_progress_pct,
    track_goidanich_incubation,
)
from .phenology import (
    PhenologyWindow,
    filter_records_by_phenology,
    get_phenology_window,
    in_phenology_window,
    season_label_for_date,
)
from .tomcast import (
    TomcastDay,
    TomcastIntervalResult,
    TomcastSprayEvent,
    compute_tomcast_daily,
    simulate_tomcast_sprays,
    tomcast_dsv_lookup,
)

__all__ = [
    "HourlyRecord",
    "load_params",
    "round_half_up",
    "PhenologyWindow",
    "get_phenology_window",
    "in_phenology_window",
    "season_label_for_date",
    "filter_records_by_phenology",
    "Rule310Event",
    "GoidanichCohort",
    "detect_rule_3_10",
    "goidanich_daily_progress_pct",
    "track_goidanich_incubation",
    "MillsEvent",
    "mills_lookup",
    "detect_mills_infections",
    "TomcastDay",
    "TomcastSprayEvent",
    "TomcastIntervalResult",
    "tomcast_dsv_lookup",
    "compute_tomcast_daily",
    "simulate_tomcast_sprays",
]
