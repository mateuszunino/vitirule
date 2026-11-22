#!/usr/bin/env python3
"""
scripts/v2_compute_reference.py
===============================
Passo 4 da Fase 1 do vitirule v2: executa o controle de qualidade cego
(`vitirule_v2.qc`) nas estacoes locais de desenvolvimento e calcula
EXCLUSIVAMENTE os alertas de referencia medida usando o sensor fisico de
molhamento foliar.

Nenhuma fonte meteorologica candidata roda neste script.
Soh deve ser executado apos a criacao da tag anotada `v2-rules`.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitirule_v2.qc import evaluate_station_season_qc
from vitirule_v2.rules import (
    compute_tomcast_daily,
    detect_mills_infections,
    detect_rule_3_10,
    simulate_tomcast_sprays,
    track_goidanich_incubation,
)
from vitirule_v2.sensors import discover_local_dev_stations, load_inrae_records, load_polito_records

PRIMARY_YEARS = (2022, 2023, 2024, 2025)
SECONDARY_LONG_YEARS = (2019, 2020, 2021)
CROPS = ("grapevine", "apple", "tomato")


def run_reference_phase1(output_path: Path | None = None) -> dict[str, Any]:
    stations = discover_local_dev_stations(ROOT / "data" / "lwd_sensors")
    qc_rows: list[dict[str, Any]] = []
    ref_rows: list[dict[str, Any]] = []

    for st in stations:
        if st.network == "inrae":
            all_records = load_inrae_records(st.path, year_min=2019, year_max=2025)
            candidate_years = list(SECONDARY_LONG_YEARS) + list(PRIMARY_YEARS)
        else:
            all_records = load_polito_records(st.path)
            observed_years = sorted({r.ts.year for r in all_records})
            candidate_years = [y for y in observed_years if y in PRIMARY_YEARS]

        # Agrupa indices por ano para filtrar rapidamente
        for yr in candidate_years:
            window_set = "primary_2022_2025" if yr in PRIMARY_YEARS else "secondary_long_2019_2021"
            yr_records = [r for r in all_records if yr - 1 <= r.ts.year <= yr + 1]

            qc_by_crop: dict[str, Any] = {}
            for crop in CROPS:
                qc = evaluate_station_season_qc(
                    raw_records=yr_records,
                    network=st.network,
                    station_id=st.station_id,
                    crop=crop,
                    season_year=yr,
                    tz_name=st.tz_name,
                    hemisphere=st.hemisphere,
                )
                qc_by_crop[crop] = qc
                row = qc.to_dict()
                row["station_name"] = st.name
                row["window_set"] = window_set
                qc_rows.append(row)

            # Calcula alertas de referencia apenas nas estacoes-safra aprovadas no QC
            # Remove registros duplicados/nulos apenas mantendo a serie limpa do ano
            clean_yr = [r for r in yr_records if r.ts.year == yr or (r.ts.year == yr - 1 and r.ts.month == 12)]

            entry: dict[str, Any] = {
                "network": st.network,
                "station_id": st.station_id,
                "station_name": st.name,
                "season_year": yr,
                "window_set": window_set,
                "rules": {},
            }

            if qc_by_crop["grapevine"].passed:
                r310 = detect_rule_3_10(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere)
                r310_yr = [e for e in r310 if e.season_label == str(yr)]
                goid = track_goidanich_incubation(
                    clean_yr,
                    trigger_dates=[e.trigger_date for e in r310_yr],
                    tz_name=st.tz_name,
                    hemisphere=st.hemisphere,
                )
                goid_done = [c for c in goid if c.completed]
                entry["rules"]["rule_3_10"] = {
                    "n_events": len(r310_yr),
                    "first_event_date": r310_yr[0].trigger_date.isoformat() if r310_yr else None,
                    "event_dates": [e.trigger_date.isoformat() for e in r310_yr],
                }
                entry["rules"]["goidanich"] = {
                    "n_cohorts": len(goid),
                    "n_completed": len(goid_done),
                    "median_duration_days": (
                        sorted(c.duration_days for c in goid_done if c.duration_days is not None)[len(goid_done) // 2]
                        if goid_done
                        else None
                    ),
                    "completion_dates": [c.completion_date.isoformat() for c in goid_done if c.completion_date],
                }

            if qc_by_crop["apple"].passed:
                mills = detect_mills_infections(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere)
                mills_yr = [m for m in mills if m.season_label == str(yr)]
                by_sev = defaultdict(int)
                for m in mills_yr:
                    by_sev[m.max_severity] += 1
                entry["rules"]["mills_revised"] = {
                    "n_events": len(mills_yr),
                    "light": by_sev["light"],
                    "moderate": by_sev["moderate"],
                    "heavy": by_sev["heavy"],
                    "first_event_ts": mills_yr[0].light_ts.isoformat() if mills_yr else None,
                }

            if qc_by_crop["tomato"].passed:
                tc_days = compute_tomcast_daily(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere)
                tc_days_yr = [d for d in tc_days if d.season_label == str(yr)]
                tc_sprays = simulate_tomcast_sprays(tc_days_yr, mode="self_reset")
                entry["rules"]["tomcast"] = {
                    "n_days": len(tc_days_yr),
                    "total_dsv": sum(d.dsv for d in tc_days_yr),
                    "n_sprays_15dsv": len(tc_sprays),
                    "spray_dates": [s.trigger_date.isoformat() for s in tc_sprays],
                }

            if entry["rules"]:
                ref_rows.append(entry)

    payload = {
        "schema_version": "2.0.0",
        "note": "Metricas agregadas de controle de qualidade e referencia medida da Fase 1. Nenhum dado bruto de terceiros incluido. Politecnico di Torino derivado de dados CC BY-NC 4.0 (DOI 10.17632/sd4b8vpvyb.1).",
        "qc_results": qc_rows,
        "reference_alerts": ref_rows,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    out = ROOT / "data" / "v2_phase1_reference_summary.json"
    res = run_reference_phase1(output_path=out)
    n_qc = len(res["qc_results"])
    n_pass = sum(1 for r in res["qc_results"] if r["passed"])
    print(f"QC avaliado: {n_pass}/{n_qc} estacoes-safra-cultura aprovadas.")
    print("Reprovacoes no QC:")
    for r in res["qc_results"]:
        if not r["passed"]:
            print(
                f"  [{r['network']}] {r['station_id']} ({r['station_name']}) "
                f"{r['season_label']} {r['crop']}: {r['reasons']} "
                f"(cov={r['coverage_frac']}, gap={r['max_gap_hours']}h, "
                f"wet={r['wet_fraction']}, dry_midday_wet={r['dry_midday_wet_fraction']}, "
                f"rainless_streak={r['max_rainless_wet_streak_h']}h)"
            )
    print(f"\nResumo salvo em {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
