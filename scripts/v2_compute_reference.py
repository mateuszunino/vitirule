#!/usr/bin/env python3
"""
scripts/v2_compute_reference.py
===============================
Executa o controle de qualidade cego sob a politica emendada
(`mask_with_warmup`, mantendo >= 95% de cobertura e todos os testes de deriva)
e sob a politica de sensibilidade original (`reject_24h`), e calcula
EXCLUSIVAMENTE os alertas de referencia medida nas estacoes locais de
desenvolvimento, aplicando o mascaramento de lacunas + aquecimento e calculando
ambas as versoes de temperatura da Regra 3-10 (`daily_min` emendada e
`daily_mean` original de `v2-rules`).

Nenhuma fonte meteorologica candidata roda neste script.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitirule_v2.qc import (
    compute_masked_hours_for_rule,
    compute_raw_gap_hours,
    evaluate_station_season_qc,
    event_touches_masked_hours,
    masked_local_days,
    rule_warmup_hours,
)
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


def run_reference_amended(output_path: Path | None = None) -> dict[str, Any]:
    stations = discover_local_dev_stations(ROOT / "data" / "lwd_sensors")
    qc_amended: list[dict[str, Any]] = []
    qc_sensitivity_24h: list[dict[str, Any]] = []
    ref_rows: list[dict[str, Any]] = []

    for st in stations:
        if st.network == "inrae":
            all_records = load_inrae_records(st.path, year_min=2019, year_max=2025)
            candidate_years = list(SECONDARY_LONG_YEARS) + list(PRIMARY_YEARS)
        else:
            all_records = load_polito_records(st.path)
            observed_years = sorted({r.ts.year for r in all_records})
            candidate_years = [y for y in observed_years if y in PRIMARY_YEARS]

        for yr in candidate_years:
            window_set = "primary_2022_2025" if yr in PRIMARY_YEARS else "secondary_long_2019_2021"
            yr_records = [r for r in all_records if yr - 1 <= r.ts.year <= yr + 1]

            qc_by_crop: dict[str, Any] = {}
            for crop in CROPS:
                q_am = evaluate_station_season_qc(
                    raw_records=yr_records,
                    network=st.network,
                    station_id=st.station_id,
                    crop=crop,
                    season_year=yr,
                    tz_name=st.tz_name,
                    hemisphere=st.hemisphere,
                    gap_policy="mask_with_warmup",
                )
                q_24 = evaluate_station_season_qc(
                    raw_records=yr_records,
                    network=st.network,
                    station_id=st.station_id,
                    crop=crop,
                    season_year=yr,
                    tz_name=st.tz_name,
                    hemisphere=st.hemisphere,
                    gap_policy="reject_24h",
                )
                qc_by_crop[crop] = q_am
                r_am = q_am.to_dict()
                r_am["station_name"] = st.name
                r_am["window_set"] = window_set
                qc_amended.append(r_am)

                r_24 = q_24.to_dict()
                r_24["station_name"] = st.name
                r_24["window_set"] = window_set
                qc_sensitivity_24h.append(r_24)

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
                mask_310_h = compute_masked_hours_for_rule(
                    yr_records, "rule_3_10", "grapevine", yr, st.tz_name, st.hemisphere
                )
                mask_310_days = masked_local_days(mask_310_h, tz_name=st.tz_name, day_start_hour=0)
                raw_gap_grape_days = masked_local_days(
                    compute_raw_gap_hours(yr_records, "grapevine", yr, st.tz_name, st.hemisphere),
                    tz_name=st.tz_name,
                    day_start_hour=0,
                )

                for agg_mode, key_suffix in (("daily_min", "daily_min"), ("daily_mean", "daily_mean")):
                    r310_raw = [
                        e for e in detect_rule_3_10(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere, temp_aggregation=agg_mode)
                        if e.season_label == str(yr)
                    ]
                    r310_clean = [
                        e for e in r310_raw
                        if (e.trigger_date not in mask_310_days)
                        and ((e.trigger_date - timedelta(days=1)) not in raw_gap_grape_days)
                    ]
                    entry["rules"][f"rule_3_10_{key_suffix}"] = {
                        "n_events_unmasked": len(r310_raw),
                        "n_events": len(r310_clean),
                        "n_masked_out": len(r310_raw) - len(r310_clean),
                        "first_event_date": r310_clean[0].trigger_date.isoformat() if r310_clean else None,
                    }

                    goid_raw = track_goidanich_incubation(
                        clean_yr,
                        trigger_dates=[e.trigger_date for e in r310_clean],
                        tz_name=st.tz_name,
                        hemisphere=st.hemisphere,
                        temp_aggregation=agg_mode,
                    )
                    goid_clean = []
                    for c in goid_raw:
                        if not c.completed or c.completion_date is None:
                            continue
                        # Exclui coorte se o gatilho (ja filtrado por 48h) ou qualquer dia de incubacao tocar lacuna
                        cur = c.trigger_date
                        touched = False
                        while cur <= c.completion_date:
                            if cur in raw_gap_grape_days:
                                touched = True
                                break
                            cur += timedelta(days=1)
                        if not touched:
                            goid_clean.append(c)
                    entry["rules"][f"goidanich_{key_suffix}"] = {
                        "n_completed_unmasked": sum(1 for c in goid_raw if c.completed),
                        "n_completed": len(goid_clean),
                        "median_duration_days": (
                            sorted(c.duration_days for c in goid_clean if c.duration_days is not None)[len(goid_clean) // 2]
                            if goid_clean
                            else None
                        ),
                    }

            if qc_by_crop["apple"].passed:
                mask_mills_h = compute_masked_hours_for_rule(
                    yr_records, "mills_revised", "apple", yr, st.tz_name, st.hemisphere
                )
                mills_raw = [
                    m for m in detect_mills_infections(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere)
                    if m.season_label == str(yr)
                ]
                mills_clean = [
                    m for m in mills_raw
                    if not event_touches_masked_hours(m.onset_ts - timedelta(hours=1), m.end_ts, mask_mills_h)
                ]
                by_sev = defaultdict(int)
                for m in mills_clean:
                    by_sev[m.max_severity] += 1
                entry["rules"]["mills_revised"] = {
                    "n_events_unmasked": len(mills_raw),
                    "n_events": len(mills_clean),
                    "n_masked_out": len(mills_raw) - len(mills_clean),
                    "light": by_sev["light"],
                    "moderate": by_sev["moderate"],
                    "heavy": by_sev["heavy"],
                }

            if qc_by_crop["tomato"].passed:
                raw_gap_tc_days = masked_local_days(
                    compute_raw_gap_hours(yr_records, "tomato", yr, st.tz_name, st.hemisphere),
                    tz_name=st.tz_name,
                    day_start_hour=12,
                )
                tc_days = [
                    d for d in compute_tomcast_daily(clean_yr, tz_name=st.tz_name, hemisphere=st.hemisphere)
                    if d.season_label == str(yr)
                ]
                tc_sprays_raw = simulate_tomcast_sprays(tc_days, mode="self_reset")
                # Exclui qualquer pulverizacao cujo intervalo de acumulacao [prev_spray+1, trigger_date] toque dia com lacuna
                tc_sprays_clean = []
                prev_spray_d = tc_days[0].day if tc_days else None
                for sp in tc_sprays_raw:
                    cur = prev_spray_d
                    touched = False
                    while cur is not None and cur <= sp.trigger_date:
                        if cur in raw_gap_tc_days:
                            touched = True
                            break
                        cur += timedelta(days=1)
                    if not touched:
                        tc_sprays_clean.append(sp)
                    prev_spray_d = sp.trigger_date + timedelta(days=1)

                entry["rules"]["tomcast"] = {
                    "n_days": len(tc_days),
                    "n_gap_days": len(raw_gap_tc_days),
                    "total_dsv": sum(d.dsv for d in tc_days),
                    "n_sprays_unmasked": len(tc_sprays_raw),
                    "n_sprays_15dsv": len(tc_sprays_clean),
                    "n_masked_out": len(tc_sprays_raw) - len(tc_sprays_clean),
                }

            if entry["rules"]:
                ref_rows.append(entry)

    payload = {
        "schema_version": "2.1.0",
        "warmup_hours_by_rule": rule_warmup_hours(),
        "qc_amended_mask_with_warmup": qc_amended,
        "qc_sensitivity_reject_24h": qc_sensitivity_24h,
        "reference_alerts": ref_rows,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    out = ROOT / "data" / "v2_phase2_reference_amended.json"
    res = run_reference_amended(output_path=out)
    print("Warm-up hours derived from params.json:", res["warmup_hours_by_rule"])
    for label, key in (("AMENDED (mask_with_warmup)", "qc_amended_mask_with_warmup"), ("SENSITIVITY (reject_24h)", "qc_sensitivity_reject_24h")):
        summary = defaultdict(lambda: [0, 0])
        for r in res[key]:
            k = (r["network"], r["window_set"], r["crop"])
            summary[k][1] += 1
            if r["passed"]:
                summary[k][0] += 1
        print(f"\n=== QC {label} ===")
        for k in sorted(summary):
            print(f"  {k[0]:8s} | {k[1]:24s} | {k[2]:10s} : {summary[k][0]}/{summary[k][1]}")
    print(f"\nSalvo em {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
