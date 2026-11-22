#!/usr/bin/env python3
"""
scripts/v2_evaluate.py
======================
Motor de avaliacao comparativa da Fase 3 do vitirule v2.

Soh deve ser executado APOS a criacao da tag anotada `v2-freeze`.
- Avaliacao exploratoria (`--split exploratory`): roda nas 4 estacoes locais do
  INRAE e nas 2 estacoes aprovadas do Politecnico di Torino (descritivo, sem IC).
- Avaliacao confirmatoria (`--split confirmatory`): roda UMA UNICA VEZ nas
  estacoes novas do INRAE aprovadas no QC cego quando o portal voltar (tag
  `v2-confirmatory`).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitirule_v2.lwd import apply_lwd_estimator
from vitirule_v2.metrics import (
    COST_LOSS_RATIOS,
    MATCH_TOLERANCES_HOURS,
    aggregate_station_metrics_with_bootstrap,
    compute_daily_cost_loss,
    match_events_one_to_one,
    mills_severity_concordance,
)
from vitirule_v2.qc import (
    compute_masked_hours_for_rule,
    compute_raw_gap_hours,
    evaluate_station_season_qc,
    event_touches_masked_hours,
    masked_local_days,
)
from vitirule_v2.rules import (
    HourlyRecord,
    compute_tomcast_daily,
    detect_mills_infections,
    detect_rule_3_10,
    simulate_tomcast_sprays,
    track_goidanich_incubation,
)
from vitirule_v2.rules.common import local_day_for_timestamp
from vitirule_v2.rules.phenology import season_date_bounds
from vitirule_v2.sensors import (
    StationMetadata,
    discover_local_dev_stations,
    load_inrae_records,
    load_polito_records,
)
from vitirule_v2.sources import (
    fetch_era5_land,
    fetch_historical_forecast,
    fetch_nasa_power_hourly,
    fetch_previous_runs,
)

UTC = timezone.utc
CACHE_DIR = ROOT / "data" / "v2_cache"


def _all_dates_in_season(yr: int, crop: str, hemisphere: str) -> list[date]:
    s, e = season_date_bounds(yr, crop=crop, hemisphere=hemisphere)
    out: list[date] = []
    cur = s
    while cur <= e:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _align_to_timestamps(
    cand_records: Sequence[HourlyRecord],
    valid_ts_set: set[datetime],
) -> list[HourlyRecord]:
    return [r for r in cand_records if r.ts in valid_ts_set]


def _load_cached_sources_for_station(st: StationMetadata, years: Sequence[int]) -> dict[str, dict[datetime, HourlyRecord]]:
    """Carrega do cache em disco (`data/v2_cache/`) todas as fontes candidatas da estacao."""
    tag = f"{st.network}_{st.station_id}"
    if st.network == "inrae":
        long_start, long_end = "2019-03-01", "2025-10-05"
        hf_start, hf_end = "2022-03-01", "2025-10-05"
        prev_years = [y for y in years if y >= 2024]
    else:
        yr0 = min(years)
        long_start, long_end = f"{yr0}-03-01", f"{yr0}-10-05"
        hf_start, hf_end = long_start, long_end
        prev_years = [y for y in years if y >= 2024]

    out: dict[str, dict[datetime, HourlyRecord]] = {}

    era_recs, _ = fetch_era5_land(st.lat, st.lon, long_start, long_end, cache_dir=CACHE_DIR, station_tag=tag)
    out["era5_land"] = {r.ts: r for r in era_recs}

    hf_recs, _ = fetch_historical_forecast(st.lat, st.lon, hf_start, hf_end, model="best_match", cache_dir=CACHE_DIR, station_tag=tag)
    out["historical_forecast"] = {r.ts: r for r in hf_recs}

    nasa_map: dict[datetime, HourlyRecord] = {}
    for yr in sorted(set(years)):
        n_recs, _ = fetch_nasa_power_hourly(st.lat, st.lon, f"{yr}-03-01", f"{yr}-10-05", cache_dir=CACHE_DIR, station_tag=f"{tag}_{yr}")
        for r in n_recs:
            nasa_map[r.ts] = r
    out["nasa_power"] = nasa_map

    for lead in (1, 2, 3):
        out[f"previous_day{lead}"] = {}
    for pyr in prev_years:
        pr_by_lead, _ = fetch_previous_runs(
            st.lat, st.lon, f"{pyr}-03-01", f"{pyr}-10-05",
            lead_days=(1, 2, 3), cache_dir=CACHE_DIR, station_tag=f"{tag}_{pyr}"
        )
        for lead in (1, 2, 3):
            for r in pr_by_lead[lead]:
                out[f"previous_day{lead}"][r.ts] = r

    return out


def _evaluate_block(
    stations: Sequence[StationMetadata],
    years: Sequence[int],
    sources: Sequence[str],
    lwd_method: str,
    rule_310_agg: str,
    gap_policy: str,
    rules_to_run: Sequence[str],
    compute_ci: bool,
    seed: int = 20261122,
) -> dict[str, Any]:
    """
    Executa avaliacao pareada estrita para um conjunto de estacoes de uma mesma
    rede, retornando metricas agregadas por regra e fonte com bootstrap em bloco
    por estacao (quando `compute_ci=True` e `n_stations >= 3`).
    """
    # Acumuladores por (regra, fonte, station_id)
    blocks: dict[tuple[str, str, str], dict[str, Any]] = {}
    mills_sev_acc: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "exact": 0, "under": 0, "over": 0})
    tc_ref_reset_acc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    n_station_seasons_by_crop: dict[str, int] = defaultdict(int)

    def _get_block(rule: str, src: str, sid: str) -> dict[str, Any]:
        key = (rule, src, sid)
        if key not in blocks:
            blocks[key] = {
                "station_id": sid,
                "tp": 0, "fp": 0, "fn": 0,
                "lags_days": [],
                "a_hit": 0, "b_false_alarm": 0, "c_miss": 0, "d_correct_neg": 0,
            }
        return blocks[key]

    for st in stations:
        if st.network == "inrae":
            all_ref = load_inrae_records(st.path, year_min=min(years), year_max=max(years))
            st_years = list(years)
        else:
            all_ref = load_polito_records(st.path)
            obs_yrs = sorted({r.ts.year for r in all_ref})
            st_years = [y for y in years if y in obs_yrs]
            if not st_years:
                continue

        cached_sources = _load_cached_sources_for_station(st, st_years)

        for yr in st_years:
            yr_ref = [r for r in all_ref if yr - 1 <= r.ts.year <= yr + 1]
            clean_yr_ref = [r for r in yr_ref if r.ts.year == yr or (r.ts.year == yr - 1 and r.ts.month == 12)]
            valid_ts_set = {r.ts for r in clean_yr_ref}

            # Constroi series alinhadas para todas as fontes candidatas sem ler `wet` do sensor
            cand_series: dict[str, list[HourlyRecord]] = {}
            for src in sources:
                if src == "station_no_sensor":
                    raw_cand = [
                        HourlyRecord(
                            ts=r.ts, temp_c=r.temp_c, rh_pct=r.rh_pct, precip_mm=r.precip_mm,
                            wet=None, wind_ms=r.wind_ms, rad_wm2=r.rad_wm2,
                        )
                        for r in clean_yr_ref
                    ]
                    cand_series[src] = apply_lwd_estimator(raw_cand, method=lwd_method, wind_height_m=2.0)
                else:
                    src_map = cached_sources[src]
                    aligned = [src_map[ts] for ts in sorted(valid_ts_set) if ts in src_map]
                    w_h = 2.0 if src == "nasa_power" else 10.0
                    cand_series[src] = apply_lwd_estimator(aligned, method=lwd_method, wind_height_m=w_h)

            # ---- VIDEIRA: Regra 3-10 e Goidanich ----
            if "rule_3_10" in rules_to_run or "goidanich" in rules_to_run:
                qc_g = evaluate_station_season_qc(
                    yr_ref, st.network, st.station_id, "grapevine", yr, st.tz_name, st.hemisphere, gap_policy=gap_policy
                )
                if qc_g.passed:
                    n_station_seasons_by_crop["grapevine"] += 1
                    mask_310_days = masked_local_days(
                        compute_masked_hours_for_rule(yr_ref, "rule_3_10", "grapevine", yr, st.tz_name, st.hemisphere),
                        tz_name=st.tz_name, day_start_hour=0,
                    )
                    raw_gap_g_days = masked_local_days(
                        compute_raw_gap_hours(yr_ref, "grapevine", yr, st.tz_name, st.hemisphere),
                        tz_name=st.tz_name, day_start_hour=0,
                    )
                    all_g_days = _all_dates_in_season(yr, "grapevine", st.hemisphere)
                    unmasked_310_days = [d for d in all_g_days if d not in mask_310_days and (d - timedelta(days=1)) not in raw_gap_g_days]
                    unmasked_goid_days = [d for d in all_g_days if d not in raw_gap_g_days]

                    ref_310 = [
                        e.trigger_date
                        for e in detect_rule_3_10(clean_yr_ref, tz_name=st.tz_name, hemisphere=st.hemisphere, temp_aggregation=rule_310_agg)
                        if e.season_label == str(yr) and e.trigger_date not in mask_310_days and (e.trigger_date - timedelta(days=1)) not in raw_gap_g_days
                    ]

                    def _clean_goid_dates(recs: list[HourlyRecord], triggers: list[date]) -> list[date]:
                        cohorts = track_goidanich_incubation(
                            recs, trigger_dates=triggers, tz_name=st.tz_name, hemisphere=st.hemisphere, temp_aggregation=rule_310_agg
                        )
                        dates_ok: list[date] = []
                        for c in cohorts:
                            if not c.completed or c.completion_date is None:
                                continue
                            cur = c.trigger_date
                            touched = False
                            while cur <= c.completion_date:
                                if cur in raw_gap_g_days:
                                    touched = True
                                    break
                                cur += timedelta(days=1)
                            if not touched:
                                dates_ok.append(c.completion_date)
                        return dates_ok

                    ref_goid = _clean_goid_dates(clean_yr_ref, ref_310)

                    for src in sources:
                        c_recs = cand_series[src]
                        cand_310 = [
                            e.trigger_date
                            for e in detect_rule_3_10(c_recs, tz_name=st.tz_name, hemisphere=st.hemisphere, temp_aggregation=rule_310_agg)
                            if e.season_label == str(yr) and e.trigger_date not in mask_310_days and (e.trigger_date - timedelta(days=1)) not in raw_gap_g_days
                        ]
                        if "rule_3_10" in rules_to_run:
                            m = match_events_one_to_one(ref_310, cand_310, MATCH_TOLERANCES_HOURS["rule_3_10"])
                            cl = compute_daily_cost_loss(unmasked_310_days, ref_310, cand_310)
                            blk = _get_block("rule_3_10", src, st.station_id)
                            blk["tp"] += m.tp; blk["fp"] += m.fp; blk["fn"] += m.fn
                            blk["lags_days"].extend(p[2] for p in m.matched_pairs)
                            for k_c in ("a_hit", "b_false_alarm", "c_miss", "d_correct_neg"):
                                blk[k_c] += cl["contingency"][k_c]

                        if "goidanich" in rules_to_run:
                            cand_goid = _clean_goid_dates(c_recs, cand_310)
                            m = match_events_one_to_one(ref_goid, cand_goid, MATCH_TOLERANCES_HOURS["goidanich"])
                            cl = compute_daily_cost_loss(unmasked_goid_days, ref_goid, cand_goid)
                            blk = _get_block("goidanich", src, st.station_id)
                            blk["tp"] += m.tp; blk["fp"] += m.fp; blk["fn"] += m.fn
                            blk["lags_days"].extend(p[2] for p in m.matched_pairs)
                            for k_c in ("a_hit", "b_false_alarm", "c_miss", "d_correct_neg"):
                                blk[k_c] += cl["contingency"][k_c]

            # ---- MACIEIRA: Tabela de Mills revisada ----
            if "mills_revised" in rules_to_run:
                qc_a = evaluate_station_season_qc(
                    yr_ref, st.network, st.station_id, "apple", yr, st.tz_name, st.hemisphere, gap_policy=gap_policy
                )
                if qc_a.passed:
                    n_station_seasons_by_crop["apple"] += 1
                    mask_m_h = compute_masked_hours_for_rule(yr_ref, "mills_revised", "apple", yr, st.tz_name, st.hemisphere)
                    mask_m_days = masked_local_days(mask_m_h, tz_name=st.tz_name, day_start_hour=0)
                    unmasked_a_days = [d for d in _all_dates_in_season(yr, "apple", st.hemisphere) if d not in mask_m_days]

                    ref_mills = [
                        e for e in detect_mills_infections(clean_yr_ref, tz_name=st.tz_name, hemisphere=st.hemisphere)
                        if e.season_label == str(yr) and not event_touches_masked_hours(e.onset_ts - timedelta(hours=1), e.end_ts, mask_m_h)
                    ]
                    ref_m_ts = [e.light_ts for e in ref_mills]
                    ref_m_sevs = [e.max_severity for e in ref_mills]
                    ref_m_days = {local_day_for_timestamp(e.light_ts, st.tz_name, 0) for e in ref_mills}

                    for src in sources:
                        cand_mills = [
                            e for e in detect_mills_infections(cand_series[src], tz_name=st.tz_name, hemisphere=st.hemisphere)
                            if e.season_label == str(yr) and not event_touches_masked_hours(e.onset_ts - timedelta(hours=1), e.end_ts, mask_m_h)
                        ]
                        cand_m_ts = [e.light_ts for e in cand_mills]
                        cand_m_sevs = [e.max_severity for e in cand_mills]
                        cand_m_days = {local_day_for_timestamp(e.light_ts, st.tz_name, 0) for e in cand_mills}

                        m = match_events_one_to_one(ref_m_ts, cand_m_ts, MATCH_TOLERANCES_HOURS["mills_revised"])
                        conc = mills_severity_concordance(ref_m_sevs, cand_m_sevs, m.matched_pairs)
                        if conc["n_matched"] > 0:
                            acc = mills_sev_acc[src]
                            acc["n"] += conc["n_matched"]
                            acc["exact"] += round(conc["exact_match_rate"] * conc["n_matched"])
                            acc["under"] += round(conc["underclassified_rate"] * conc["n_matched"])
                            acc["over"] += round(conc["overclassified_rate"] * conc["n_matched"])

                        cl = compute_daily_cost_loss(unmasked_a_days, ref_m_days, cand_m_days)
                        blk = _get_block("mills_revised", src, st.station_id)
                        blk["tp"] += m.tp; blk["fp"] += m.fp; blk["fn"] += m.fn
                        blk["lags_days"].extend(p[2] for p in m.matched_pairs)
                        for k_c in ("a_hit", "b_false_alarm", "c_miss", "d_correct_neg"):
                            blk[k_c] += cl["contingency"][k_c]

            # ---- TOMATEIRO: TOM-CAST (self_reset + reference_reset) ----
            if "tomcast_self" in rules_to_run or "tomcast_ref_reset" in rules_to_run:
                qc_t = evaluate_station_season_qc(
                    yr_ref, st.network, st.station_id, "tomato", yr, st.tz_name, st.hemisphere, gap_policy=gap_policy
                )
                if qc_t.passed:
                    n_station_seasons_by_crop["tomato"] += 1
                    raw_gap_t_days = masked_local_days(
                        compute_raw_gap_hours(yr_ref, "tomato", yr, st.tz_name, st.hemisphere),
                        tz_name=st.tz_name, day_start_hour=12,
                    )
                    unmasked_t_days = [d for d in _all_dates_in_season(yr, "tomato", st.hemisphere) if d not in raw_gap_t_days]

                    ref_tc_days = [
                        d for d in compute_tomcast_daily(clean_yr_ref, tz_name=st.tz_name, hemisphere=st.hemisphere)
                        if d.season_label == str(yr)
                    ]
                    ref_tc_sprays_all = simulate_tomcast_sprays(ref_tc_days, mode="self_reset")

                    def _filter_tc_sprays(days_list, sprays_list) -> list[date]:
                        out_d: list[date] = []
                        prev_d = days_list[0].day if days_list else None
                        for sp in sprays_list:
                            cur = prev_d
                            touched = False
                            while cur is not None and cur <= sp.trigger_date:
                                if cur in raw_gap_t_days:
                                    touched = True
                                    break
                                cur += timedelta(days=1)
                            if not touched:
                                out_d.append(sp.trigger_date)
                            prev_d = sp.trigger_date + timedelta(days=1)
                        return out_d

                    ref_tc_clean = _filter_tc_sprays(ref_tc_days, ref_tc_sprays_all)
                    ref_tc_all_dates = [s.trigger_date for s in ref_tc_sprays_all]

                    for src in sources:
                        cand_tc_days = [
                            d for d in compute_tomcast_daily(cand_series[src], tz_name=st.tz_name, hemisphere=st.hemisphere)
                            if d.season_label == str(yr)
                        ]
                        if "tomcast_self" in rules_to_run:
                            cand_tc_sprays_all = simulate_tomcast_sprays(cand_tc_days, mode="self_reset")
                            cand_tc_clean = _filter_tc_sprays(cand_tc_days, cand_tc_sprays_all)
                            m = match_events_one_to_one(ref_tc_clean, cand_tc_clean, MATCH_TOLERANCES_HOURS["tomcast_self"])
                            cl = compute_daily_cost_loss(unmasked_t_days, ref_tc_clean, cand_tc_clean)
                            blk = _get_block("tomcast_self", src, st.station_id)
                            blk["tp"] += m.tp; blk["fp"] += m.fp; blk["fn"] += m.fn
                            blk["lags_days"].extend(p[2] for p in m.matched_pairs)
                            for k_c in ("a_hit", "b_false_alarm", "c_miss", "d_correct_neg"):
                                blk[k_c] += cl["contingency"][k_c]

                        if "tomcast_ref_reset" in rules_to_run:
                            intervals = simulate_tomcast_sprays(
                                cand_tc_days, mode="reference_reset", reference_spray_dates=ref_tc_all_dates
                            )
                            for iv in intervals:
                                # Exclui intervalo se tocar dia com lacuna
                                end_iv = iv.reference_spray_date or (cand_tc_days[-1].day if cand_tc_days else iv.interval_start_date)
                                cur = iv.interval_start_date
                                touched = False
                                while cur <= end_iv:
                                    if cur in raw_gap_t_days:
                                        touched = True
                                        break
                                    cur += timedelta(days=1)
                                if not touched:
                                    tc_ref_reset_acc[src].append({
                                        "station_id": st.station_id,
                                        "year": yr,
                                        "is_ref_interval": iv.reference_spray_date is not None,
                                        "reached_by_ref": iv.reached_by_ref_date,
                                        "lead_days": iv.lead_days,
                                        "dsv_at_ref": iv.candidate_dsv_at_ref,
                                        "dsv_error": iv.candidate_dsv_at_ref - 15 if iv.reference_spray_date is not None else None,
                                    })

    # Agrega resultados por regra e fonte
    results: dict[str, Any] = {
        "n_station_seasons_by_crop": dict(n_station_seasons_by_crop),
        "by_rule": {},
    }
    for rule in rules_to_run:
        if rule == "tomcast_ref_reset":
            rr_out: dict[str, Any] = {}
            for src in sources:
                ivs = [x for x in tc_ref_reset_acc[src] if x["is_ref_interval"]]
                trailing_fp = sum(1 for x in tc_ref_reset_acc[src] if not x["is_ref_interval"])
                n_iv = len(ivs)
                reached = sum(1 for x in ivs if x["reached_by_ref"])
                leads = sorted(x["lead_days"] for x in ivs if x["lead_days"] is not None)
                dsv_errs = [x["dsv_error"] for x in ivs if x["dsv_error"] is not None]
                rr_out[src] = {
                    "n_ref_intervals": n_iv,
                    "n_reached_by_ref": reached,
                    "reached_rate": round(reached / n_iv, 4) if n_iv else None,
                    "missed_by_ref_rate": round((n_iv - reached) / n_iv, 4) if n_iv else None,
                    "median_lead_days_when_reached": leads[len(leads) // 2] if leads else None,
                    "mean_dsv_error_at_ref": round(sum(dsv_errs) / len(dsv_errs), 2) if dsv_errs else None,
                    "trailing_false_alarms": trailing_fp,
                }
            results["by_rule"]["tomcast_ref_reset"] = rr_out
            continue

        rule_out: dict[str, Any] = {}
        for src in sources:
            st_blocks = [
                blocks[(rule, src, st.station_id)]
                for st in stations
                if (rule, src, st.station_id) in blocks
            ]
            agg = aggregate_station_metrics_with_bootstrap(
                st_blocks,
                cost_loss_ratios=COST_LOSS_RATIOS,
                n_boot=2000,
                seed=seed,
                compute_ci=compute_ci,
            )
            if rule == "mills_revised":
                acc = mills_sev_acc[src]
                n_m = acc["n"]
                agg["severity_concordance"] = {
                    "n_matched": n_m,
                    "exact_match_rate": round(acc["exact"] / n_m, 4) if n_m else None,
                    "underclassified_rate": round(acc["under"] / n_m, 4) if n_m else None,
                    "overclassified_rate": round(acc["over"] / n_m, 4) if n_m else None,
                }
            rule_out[src] = agg
        results["by_rule"][rule] = rule_out

    return results


def run_exploratory(output_path: Path) -> dict[str, Any]:
    stations = discover_local_dev_stations(ROOT / "data" / "lwd_sensors")
    inrae_st = [s for s in stations if s.network == "inrae"]
    polito_st = [s for s in stations if s.network == "polito"]

    primary_sources = ("station_no_sensor", "era5_land", "historical_forecast", "nasa_power")
    all_rules = ("rule_3_10", "goidanich", "mills_revised", "tomcast_self", "tomcast_ref_reset")

    report: dict[str, Any] = {
        "schema_version": "2.0.0",
        "split": "exploratory",
        "note": (
            "Avaliacao exploratoria apos a tag v2-freeze sobre as 4 estacoes locais do INRAE "
            "e as 2 estacoes aprovadas do Politecnico di Torino (descritivo, sem IC). "
            "Politecnico derivado de dados CC BY-NC 4.0 (DOI 10.17632/sd4b8vpvyb.1)."
        ),
        "primary_analysis_2022_2025": {
            "spec": {
                "years": [2022, 2023, 2024, 2025],
                "lwd_method": "rh90_rain",
                "rule_3_10_temp": "daily_min",
                "gap_policy": "mask_with_warmup",
            },
            "inrae_exploratory": _evaluate_block(
                inrae_st, (2022, 2023, 2024, 2025), primary_sources,
                lwd_method="rh90_rain", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                rules_to_run=all_rules, compute_ci=True,
            ),
            "polito_exploratory_descriptive_only": _evaluate_block(
                polito_st, (2022, 2023, 2024, 2025), primary_sources,
                lwd_method="rh90_rain", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                rules_to_run=all_rules, compute_ci=False,
            ),
        },
        "secondary_analyses": {
            "lwd_dpd_hysteresis_2022_2025": {
                "inrae": _evaluate_block(
                    inrae_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="dpd_hysteresis", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                    rules_to_run=("mills_revised", "tomcast_self", "tomcast_ref_reset"), compute_ci=True,
                ),
                "polito_descriptive_only": _evaluate_block(
                    polito_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="dpd_hysteresis", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                    rules_to_run=("mills_revised", "tomcast_self", "tomcast_ref_reset"), compute_ci=False,
                ),
            },
            "lwd_cart_kim2002_2022_2025": {
                "inrae": _evaluate_block(
                    inrae_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="cart_kim2002", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                    rules_to_run=("mills_revised", "tomcast_self", "tomcast_ref_reset"), compute_ci=True,
                ),
                "polito_descriptive_only": _evaluate_block(
                    polito_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="cart_kim2002", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                    rules_to_run=("mills_revised", "tomcast_self", "tomcast_ref_reset"), compute_ci=False,
                ),
            },
            "rule_3_10_daily_mean_v2_rules_2022_2025": {
                "inrae": _evaluate_block(
                    inrae_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="rh90_rain", rule_310_agg="daily_mean", gap_policy="mask_with_warmup",
                    rules_to_run=("rule_3_10", "goidanich"), compute_ci=True,
                ),
                "polito_descriptive_only": _evaluate_block(
                    polito_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="rh90_rain", rule_310_agg="daily_mean", gap_policy="mask_with_warmup",
                    rules_to_run=("rule_3_10", "goidanich"), compute_ci=False,
                ),
            },
            "qc_sensitivity_reject_24h_2022_2025": {
                "inrae": _evaluate_block(
                    inrae_st, (2022, 2023, 2024, 2025), primary_sources,
                    lwd_method="rh90_rain", rule_310_agg="daily_min", gap_policy="reject_24h",
                    rules_to_run=all_rules, compute_ci=True,
                ),
            },
            "secondary_A_long_2019_2025_inrae": _evaluate_block(
                inrae_st, (2019, 2020, 2021, 2022, 2023, 2024, 2025),
                ("station_no_sensor", "era5_land", "nasa_power"),
                lwd_method="rh90_rain", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                rules_to_run=all_rules, compute_ci=True,
            ),
            "secondary_B_previous_runs_2024_2025_inrae": _evaluate_block(
                inrae_st, (2024, 2025),
                ("historical_forecast", "previous_day1", "previous_day2", "previous_day3"),
                lwd_method="rh90_rain", rule_310_agg="daily_min", gap_policy="mask_with_warmup",
                rules_to_run=all_rules, compute_ci=True,
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliacao da Fase 3 do vitirule v2.")
    parser.add_argument("--split", choices=("exploratory",), default="exploratory")
    parser.add_argument("--out", default="data/v2_phase3_exploratory_results.json")
    args = parser.parse_args(argv)

    out_path = ROOT / args.out
    run_exploratory(out_path)
    print(f"Avaliacao exploratoria concluida e salva em {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
