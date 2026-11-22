#!/usr/bin/env python3
"""
scripts/v2_phase4_brazil.py
===========================
Fase 4 do vitirule v2: transferencia brasileira em Santa Catarina usando
estacoes automaticas horarias do INMET sob a regra congelada em `v2-freeze-br`
(Secao 9 de `docs/v2/preregistro.md`).

Restricoes congeladas em `v2-freeze-br`:
- Selecao objetiva: todas as estacoes automaticas do INMET em SC sediadas em
  municipios produtores de maca, uva ou tomate segundo IBGE PAM (SIDRA 5457)
  com pelo menos N = 2 safras aprovadas no QC cego (`require_lwd_sensor=False`,
  `mask_with_warmup`) no recorte pareado 2022-2025 do Hemisferio Sul.
- Interpretacao obrigatoria:
  - Mills revisada: estimativa de erro da grade (sujeita a `v2-confirmatory`).
  - Regra 3-10, Goidanich e TOM-CAST: estritamente DIVERGENCIA, nunca erro.
- Diagnostico por relevo e regime de chuva: estritamente EXPLORATORIO.
- Sem leitor Epagri/Ciram nesta etapa.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

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
from vitirule_v2.sources import (
    build_station_grid_match,
    fetch_era5_025_grid_meta,
    fetch_era5_combined,
    fetch_historical_forecast,
    fetch_nasa_power_hourly,
)
from vitirule_v2.sources.inmet import (
    InmetStationInfo,
    discover_inmet_sc_stations,
    download_inmet_sc_zips,
    fetch_ibge_pam_sc_producers,
    is_producing_municipality,
    load_inmet_station_records,
)

UTC = timezone.utc
TZ_SC = "America/Sao_Paulo"
HEMISPHERE = "southern_hemisphere"
INMET_DIR = ROOT / "data" / "inmet_sc"
CACHE_DIR = ROOT / "data" / "v2_cache"
MIN_SEASONS_PER_CROP = 2

CROP_SEASONS = {
    "apple": (2022, 2023, 2024, 2025),
    "grapevine": (2022, 2023, 2024),
    "tomato": (2022, 2023, 2024),
}

GRID_SOURCES = ("era5_combined", "historical_forecast", "nasa_power")


def _all_dates_in_season(yr: int, crop: str) -> list[date]:
    s, e = season_date_bounds(yr, crop=crop, hemisphere=HEMISPHERE)
    out: list[date] = []
    cur = s
    while cur <= e:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _spearman_corr(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 4 or len(xs) != len(ys):
        return None

    def _ranks(vals: Sequence[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda kv: kv[1])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_r = 0.5 * (i + j) + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_r
            i = j + 1
        return ranks

    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0.0 or dy == 0.0:
        return None
    return round(num / (dx * dy), 4)


def _fetch_sources_for_inmet_station(
    st: InmetStationInfo,
    session: requests.Session,
) -> tuple[dict[str, dict[datetime, HourlyRecord]], list[dict[str, Any]]]:
    tag = f"inmet_sc_{st.station_id}"
    start_str, end_str = "2022-09-01", "2025-12-31"
    matches: list[dict[str, Any]] = []
    out: dict[str, dict[datetime, HourlyRecord]] = {}

    # 1. ERA5 combinado (era5_seamless) + metadado 0,25 grau (era5)
    era_recs, era_meta = fetch_era5_combined(
        st.lat, st.lon, start_str, end_str, cache_dir=CACHE_DIR, station_tag=tag, session=session
    )
    out["era5_combined"] = {r.ts: r for r in era_recs}
    matches.append(
        build_station_grid_match(
            "inmet_sc", st.station_id, st.station_name, "era5_combined_t_rh_010",
            st.lat, st.lon, st.elevation_m,
            era_meta["grid_lat"], era_meta["grid_lon"], era_meta["grid_elev_m"],
            model_note="era5_seamless: T e UR do ERA5-Land (0,1 grau)",
        ).to_dict()
    )
    era025_meta = fetch_era5_025_grid_meta(
        st.lat, st.lon, sample_date="2022-11-01", cache_dir=CACHE_DIR, station_tag=tag, session=session
    )
    matches.append(
        build_station_grid_match(
            "inmet_sc", st.station_id, st.station_name, "era5_combined_precip_025",
            st.lat, st.lon, st.elevation_m,
            era025_meta["grid_lat"], era025_meta["grid_lon"], era025_meta["grid_elev_m"],
            model_note="era5_seamless: chuva, vento e radiacao do ERA5 (0,25 grau)",
        ).to_dict()
    )
    time.sleep(0.0)

    # 2. Historical Forecast
    hf_recs, hf_meta = fetch_historical_forecast(
        st.lat, st.lon, start_str, end_str, model="best_match",
        cache_dir=CACHE_DIR, station_tag=tag, session=session
    )
    out["historical_forecast"] = {r.ts: r for r in hf_recs}
    matches.append(
        build_station_grid_match(
            "inmet_sc", st.station_id, st.station_name, "historical_forecast",
            st.lat, st.lon, st.elevation_m,
            hf_meta["grid_lat"], hf_meta["grid_lon"], hf_meta["grid_elev_m"],
            model_note=str(hf_meta.get("model", "")),
        ).to_dict()
    )
    time.sleep(0.0)

    # 3. NASA POWER hourly (explicit time-standard=UTC), baixado por ano
    nasa_map: dict[datetime, HourlyRecord] = {}
    nasa_meta_saved: dict[str, Any] | None = None
    for yr in (2022, 2023, 2024, 2025):
        ys = "2022-09-01" if yr == 2022 else f"{yr}-01-01"
        ye = f"{yr}-12-31"
        n_recs, n_meta = fetch_nasa_power_hourly(
            st.lat, st.lon, ys, ye, cache_dir=CACHE_DIR, station_tag=f"{tag}_{yr}", session=session
        )
        for r in n_recs:
            nasa_map[r.ts] = r
        if nasa_meta_saved is None:
            nasa_meta_saved = n_meta
        time.sleep(0.0)
    assert nasa_meta_saved is not None
    out["nasa_power"] = nasa_map
    matches.append(
        build_station_grid_match(
            "inmet_sc", st.station_id, st.station_name, "nasa_power",
            st.lat, st.lon, st.elevation_m,
            nasa_meta_saved["grid_lat"], nasa_meta_saved["grid_lon"], nasa_meta_saved["grid_elev_m"],
            model_note=f"{nasa_meta_saved['model']} (time_standard={nasa_meta_saved['time_standard']})",
        ).to_dict()
    )
    return out, matches


def _prepare_candidate(
    src_map: dict[datetime, HourlyRecord],
    valid_ts: list[datetime],
) -> list[HourlyRecord]:
    raw = [src_map[ts] for ts in valid_ts if ts in src_map]
    return apply_lwd_estimator(raw, method="rh90_rain", wind_height_m=10.0)


def _evaluate_rule_on_station_season(
    rule_name: str,
    crop: str,
    yr: int,
    base_recs: list[HourlyRecord],
    cand_recs: list[HourlyRecord],
) -> dict[str, Any]:
    """
    Aplica a regra congelada em `base_recs` (estacao INMET com `rh90_rain`) e
    `cand_recs` (fonte em grade com `rh90_rain`) sob a mesma mascara de lacunas.
    """
    masked_h = compute_masked_hours_for_rule(
        base_recs, rule_name, crop, yr, TZ_SC, hemisphere=HEMISPHERE, require_lwd_sensor=False
    )
    raw_gap_h = compute_raw_gap_hours(
        base_recs, crop, yr, TZ_SC, hemisphere=HEMISPHERE, require_lwd_sensor=False
    )
    all_days = _all_dates_in_season(yr, crop)

    if rule_name == "rule_3_10":
        masked_d = masked_local_days(masked_h, TZ_SC, day_start_hour=0)
        unmasked_days = [d for d in all_days if d not in masked_d]
        ref_evs = [
            e for e in detect_rule_3_10(base_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE, temp_aggregation="daily_min")
            if e.trigger_date in unmasked_days
        ]
        cand_evs = [
            e for e in detect_rule_3_10(cand_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE, temp_aggregation="daily_min")
            if e.trigger_date in unmasked_days
        ]
        ref_t = [datetime(e.trigger_date.year, e.trigger_date.month, e.trigger_date.day, tzinfo=UTC) for e in ref_evs]
        cand_t = [datetime(e.trigger_date.year, e.trigger_date.month, e.trigger_date.day, tzinfo=UTC) for e in cand_evs]
        m = match_events_one_to_one(ref_t, cand_t, MATCH_TOLERANCES_HOURS["rule_3_10"])
        cl = compute_daily_cost_loss(unmasked_days, {e.trigger_date for e in ref_evs}, {e.trigger_date for e in cand_evs})
        return {"match": m.to_dict(), "cost_loss": cl}

    if rule_name == "goidanich":
        r310_masked = compute_masked_hours_for_rule(
            base_recs, "rule_3_10", crop, yr, TZ_SC, hemisphere=HEMISPHERE, require_lwd_sensor=False
        )
        r310_masked_d = masked_local_days(r310_masked, TZ_SC, day_start_hour=0)
        gap_d = masked_local_days(raw_gap_h, TZ_SC, day_start_hour=0)
        unmasked_days = [d for d in all_days if d not in gap_d]

        def _valid_goid(recs: list[HourlyRecord]) -> list[Any]:
            r310 = [
                e for e in detect_rule_3_10(recs, tz_name=TZ_SC, hemisphere=HEMISPHERE, temp_aggregation="daily_min")
                if e.trigger_date not in r310_masked_d
            ]
            cohorts = track_goidanich_incubation(
                recs, [e.trigger_date for e in r310], tz_name=TZ_SC, hemisphere=HEMISPHERE
            )
            valid = []
            for c in cohorts:
                if c.completion_date is None or c.completion_date not in unmasked_days:
                    continue
                if any(c.trigger_date <= gd <= c.completion_date for gd in gap_d):
                    continue
                valid.append(c)
            return valid

        ref_c = _valid_goid(base_recs)
        cand_c = _valid_goid(cand_recs)
        ref_t = [datetime(c.completion_date.year, c.completion_date.month, c.completion_date.day, tzinfo=UTC) for c in ref_c]
        cand_t = [datetime(c.completion_date.year, c.completion_date.month, c.completion_date.day, tzinfo=UTC) for c in cand_c]
        m = match_events_one_to_one(ref_t, cand_t, MATCH_TOLERANCES_HOURS["goidanich"])
        cl = compute_daily_cost_loss(unmasked_days, {c.completion_date for c in ref_c}, {c.completion_date for c in cand_c})
        return {"match": m.to_dict(), "cost_loss": cl}

    if rule_name == "mills_revised":
        masked_d = masked_local_days(masked_h, TZ_SC, day_start_hour=0)
        unmasked_days = [d for d in all_days if d not in masked_d]
        ref_evs = [
            e for e in detect_mills_infections(base_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE)
            if not event_touches_masked_hours(e.onset_ts - timedelta(hours=1), e.end_ts, masked_h)
            and local_day_for_timestamp(e.light_ts, TZ_SC) in unmasked_days
        ]
        cand_evs = [
            e for e in detect_mills_infections(cand_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE)
            if not event_touches_masked_hours(e.onset_ts - timedelta(hours=1), e.end_ts, masked_h)
            and local_day_for_timestamp(e.light_ts, TZ_SC) in unmasked_days
        ]
        m = match_events_one_to_one([e.light_ts for e in ref_evs], [e.light_ts for e in cand_evs], MATCH_TOLERANCES_HOURS["mills_revised"])
        sev = mills_severity_concordance([e.max_severity for e in ref_evs], [e.max_severity for e in cand_evs], m.matched_pairs)
        ref_days = {local_day_for_timestamp(e.light_ts, TZ_SC) for e in ref_evs}
        cand_days = {local_day_for_timestamp(e.light_ts, TZ_SC) for e in cand_evs}
        cl = compute_daily_cost_loss(unmasked_days, ref_days, cand_days)
        return {"match": m.to_dict(), "severity": sev, "cost_loss": cl}

    if rule_name == "tomcast":
        gap_d = masked_local_days(raw_gap_h, TZ_SC, day_start_hour=12)
        unmasked_days = [d for d in all_days if d not in gap_d]

        ref_daily = compute_tomcast_daily(base_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE)
        cand_daily = compute_tomcast_daily(cand_recs, tz_name=TZ_SC, hemisphere=HEMISPHERE)
        season_start = all_days[0]

        def _valid_self_sprays(daily_rows: list[Any]) -> list[Any]:
            sprays = simulate_tomcast_sprays(daily_rows, mode="self_reset")
            out_sp = []
            prev = season_start - timedelta(days=1)
            for sp in sprays:
                if sp.trigger_date in unmasked_days and not any(prev < gd <= sp.trigger_date for gd in gap_d):
                    out_sp.append(sp)
                prev = sp.trigger_date
            return out_sp

        ref_sp = _valid_self_sprays(ref_daily)
        cand_sp = _valid_self_sprays(cand_daily)
        ref_t = [datetime(s.trigger_date.year, s.trigger_date.month, s.trigger_date.day, tzinfo=UTC) for s in ref_sp]
        cand_t = [datetime(s.trigger_date.year, s.trigger_date.month, s.trigger_date.day, tzinfo=UTC) for s in cand_sp]
        m = match_events_one_to_one(ref_t, cand_t, MATCH_TOLERANCES_HOURS["tomcast_self"])
        cl = compute_daily_cost_loss(unmasked_days, {s.trigger_date for s in ref_sp}, {s.trigger_date for s in cand_sp})

        # Modo reference_reset (fidelidade da entrada contra a estacao INMET)
        ref_dates_all = [s.trigger_date for s in simulate_tomcast_sprays(ref_daily, mode="self_reset")]
        valid_ref_dates = {s.trigger_date for s in ref_sp}
        ref_reset_ivs = simulate_tomcast_sprays(cand_daily, mode="reference_reset", reference_spray_dates=ref_dates_all)
        valid_intervals = [iv for iv in ref_reset_ivs if iv.reference_spray_date in valid_ref_dates]
        extra_fa = sum(1 for iv in ref_reset_ivs if iv.reference_spray_date is None and iv.candidate_trigger_date in unmasked_days)
        return {
            "match": m.to_dict(),
            "cost_loss": cl,
            "ref_reset": {
                "n_intervals": len(valid_intervals),
                "n_reached": sum(1 for iv in valid_intervals if iv.reached_by_ref_date),
                "dsv_errors": [int(iv.candidate_dsv_at_ref) - 15 for iv in valid_intervals],
                "lead_days": [iv.lead_days for iv in valid_intervals if iv.lead_days is not None],
                "extra_false_alarms": extra_fa,
            },
        }

    raise ValueError(f"regra desconhecida: {rule_name}")


def _aggregate_rule_across_stations(
    rule_name: str,
    crop: str,
    interpretation: str,
    station_rows_by_source: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in GRID_SOURCES:
        by_st = station_rows_by_source[src]
        station_blocks: list[dict[str, Any]] = []
        per_station_summary: dict[str, dict[str, Any]] = {}
        sev_n = sev_exact = sev_under = sev_over = 0
        rr_n = rr_reached = rr_extra = 0
        rr_dsv_errs: list[int] = []
        rr_leads: list[int] = []

        for sid, srows in sorted(by_st.items()):
            tp = sum(int(x["match"]["tp"]) for x in srows)
            fp = sum(int(x["match"]["fp"]) for x in srows)
            fn = sum(int(x["match"]["fn"]) for x in srows)
            lags: list[float] = []
            a_hit = b_fa = c_miss = d_tn = 0
            for x in srows:
                lags.extend(float(p[2]) for p in x["match"]["matched_pairs"])
                cont = x["cost_loss"]["contingency"]
                a_hit += int(cont["a_hit"])
                b_fa += int(cont["b_false_alarm"])
                c_miss += int(cont["c_miss"])
                d_tn += int(cont["d_correct_neg"])
                if "severity" in x:
                    sn = int(x["severity"]["n_matched"])
                    sev_n += sn
                    if sn > 0:
                        sev_exact += round(x["severity"]["exact_match_rate"] * sn)
                        sev_under += round(x["severity"]["underclassified_rate"] * sn)
                        sev_over += round(x["severity"]["overclassified_rate"] * sn)
                if "ref_reset" in x:
                    rr_n += x["ref_reset"]["n_intervals"]
                    rr_reached += x["ref_reset"]["n_reached"]
                    rr_extra += x["ref_reset"]["extra_false_alarms"]
                    rr_dsv_errs.extend(x["ref_reset"]["dsv_errors"])
                    rr_leads.extend(x["ref_reset"]["lead_days"])

            station_blocks.append({
                "station_id": sid,
                "tp": tp, "fp": fp, "fn": fn,
                "lags_days": lags,
                "a_hit": a_hit, "b_false_alarm": b_fa, "c_miss": c_miss, "d_correct_neg": d_tn,
            })
            per_station_summary[sid] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "miss_rate": round(fn / (tp + fn), 4) if (tp + fn) else None,
                "far": round(fp / (tp + fp), 4) if (tp + fp) else None,
                "f1": round(2 * tp / (2 * tp + fp + fn), 4) if (2 * tp + fp + fn) else None,
            }

        agg = aggregate_station_metrics_with_bootstrap(station_blocks, n_boot=2000, seed=20261122)
        agg["interpretation"] = interpretation
        agg["n_station_seasons"] = sum(len(v) for v in by_st.values())
        agg["per_station"] = per_station_summary

        if rule_name == "mills_revised":
            agg["severity"] = {
                "n_matched": sev_n,
                "exact_match_rate": round(sev_exact / sev_n, 4) if sev_n else None,
                "underclassified_rate": round(sev_under / sev_n, 4) if sev_n else None,
                "overclassified_rate": round(sev_over / sev_n, 4) if sev_n else None,
            }
        if rule_name == "tomcast":
            rr_leads_sorted = sorted(rr_leads)
            med_lead = rr_leads_sorted[len(rr_leads_sorted) // 2] if rr_leads_sorted else None
            agg["reference_reset"] = {
                "n_intervals": rr_n,
                "reached_frac": round(rr_reached / rr_n, 4) if rr_n else None,
                "mean_dsv_error": round(sum(rr_dsv_errs) / len(rr_dsv_errs), 2) if rr_dsv_errs else None,
                "median_lead_days": med_lead,
                "extra_false_alarms": rr_extra,
            }
        out[src] = agg
    return out


def main() -> int:
    session = requests.Session()
    download_inmet_sc_zips(INMET_DIR, years=(2022, 2023, 2024, 2025), session=session)
    stations = discover_inmet_sc_stations(INMET_DIR, years=(2022, 2023, 2024, 2025))
    pam = fetch_ibge_pam_sc_producers(2025, cache_path=INMET_DIR / "ibge_pam_sc_2025.json", session=session)

    # 1. Selecao cega sob v2-freeze-br
    selection_table: list[dict[str, Any]] = []
    passing_seasons_by_crop: dict[str, dict[str, list[int]]] = {c: {} for c in CROP_SEASONS}
    records_by_station: dict[str, list[HourlyRecord]] = {}
    station_by_id: dict[str, InmetStationInfo] = {}

    for st in stations:
        station_by_id[st.station_id] = st
        prow = pam.get(st.municipality_key)
        is_prod = is_producing_municipality(prow)
        recs = load_inmet_station_records(st.csv_paths)
        records_by_station[st.station_id] = recs

        qc_summary: dict[str, list[dict[str, Any]]] = {}
        pass_counts: dict[str, int] = {}
        selected_crops: list[str] = []

        for crop, yrs in CROP_SEASONS.items():
            c_rows = []
            passed_yrs = []
            for yr in yrs:
                res = evaluate_station_season_qc(
                    recs, "inmet_sc", st.station_id, crop, yr, TZ_SC,
                    hemisphere=HEMISPHERE, gap_policy="mask_with_warmup", require_lwd_sensor=False,
                )
                c_rows.append({
                    "season": res.season_label,
                    "year": yr,
                    "passed": res.passed,
                    "coverage_frac": res.coverage_frac,
                    "max_gap_hours": res.max_gap_hours,
                    "reasons": list(res.reasons),
                })
                if res.passed:
                    passed_yrs.append(yr)
            qc_summary[crop] = c_rows
            pass_counts[crop] = len(passed_yrs)
            if is_prod and len(passed_yrs) >= MIN_SEASONS_PER_CROP:
                passing_seasons_by_crop[crop][st.station_id] = passed_yrs
                selected_crops.append(crop)

        if not is_prod:
            status_reason = "excluida_filtro_ibge_pam_sem_producao"
        elif not selected_crops:
            status_reason = "excluida_qc_menos_de_2_safras"
        else:
            status_reason = "incluida"

        selection_table.append({
            "station_id": st.station_id,
            "station_name": st.station_name,
            "municipality_key": st.municipality_key,
            "lat": st.lat,
            "lon": st.lon,
            "elevation_m": st.elevation_m,
            "ibge_pam_2025": prow or {"maca_ha": 0.0, "tomate_ha": 0.0, "uva_ha": 0.0},
            "is_producing_municipality": is_prod,
            "qc_pass_counts": pass_counts,
            "selected_crops": selected_crops,
            "status": status_reason,
            "qc_details": qc_summary,
        })

    selected_station_ids = sorted({
        sid for crop_map in passing_seasons_by_crop.values() for sid in crop_map
    })
    print(f"Estacoes SC totais: {len(stations)} | Selecionadas em >= 1 cultura (v2-freeze-br): {len(selected_station_ids)}")
    for c in CROP_SEASONS:
        n_ss = sum(len(v) for v in passing_seasons_by_crop[c].values())
        print(f"  {c:10s}: {len(passing_seasons_by_crop[c])} estacoes, {n_ss} estacoes-safra")

    # 2. Coleta das 3 fontes em grade + metadados espaciais (0,1 e 0,25 grau) para todas as selecionadas
    grid_matches: list[dict[str, Any]] = []
    sources_by_station: dict[str, dict[str, dict[datetime, HourlyRecord]]] = {}
    for sid in selected_station_ids:
        st = station_by_id[sid]
        print(f"  Coletando fontes em grade para {sid} ({st.station_name}, {st.elevation_m}m) ...", flush=True)
        src_maps, matches = _fetch_sources_for_inmet_station(st, session)
        sources_by_station[sid] = src_maps
        grid_matches.extend(matches)

    # 3. Avaliacao das 4 regras (Mills = estimativa de erro; demais = divergencia)
    rule_specs = [
        ("rule_3_10", "grapevine", "divergencia_apenas_nao_erro"),
        ("goidanich", "grapevine", "divergencia_apenas_nao_erro"),
        ("mills_revised", "apple", "estimativa_de_erro_da_grade"),
        ("tomcast", "tomato", "divergencia_apenas_nao_erro"),
    ]
    results_by_rule: dict[str, Any] = {}
    for rule_name, crop, interp in rule_specs:
        station_rows_by_source: dict[str, dict[str, list[dict[str, Any]]]] = {s: defaultdict(list) for s in GRID_SOURCES}
        for sid, yrs in sorted(passing_seasons_by_crop[crop].items()):
            base_all = records_by_station[sid]
            base_lwd_all = apply_lwd_estimator(base_all, method="rh90_rain", wind_height_m=10.0)
            base_by_ts = {r.ts: r for r in base_lwd_all}

            for yr in yrs:
                s_d, e_d = season_date_bounds(yr, crop=crop, hemisphere=HEMISPHERE)
                pad_s = datetime(s_d.year, s_d.month, s_d.day, 0, 0, tzinfo=UTC) - timedelta(days=3)
                pad_e = datetime(e_d.year, e_d.month, e_d.day, 23, 0, tzinfo=UTC) + timedelta(days=3)
                win_ts = [ts for ts in sorted(base_by_ts) if pad_s <= ts <= pad_e]
                base_win = [base_by_ts[ts] for ts in win_ts]

                for src in GRID_SOURCES:
                    cand_win = _prepare_candidate(sources_by_station[sid][src], win_ts)
                    ev = _evaluate_rule_on_station_season(rule_name, crop, yr, base_win, cand_win)
                    station_rows_by_source[src][sid].append(ev)

        results_by_rule[rule_name] = _aggregate_rule_across_stations(
            rule_name, crop, interp, station_rows_by_source
        )

    # 4. Diagnostico EXPLORATORIO por relevo e regime de chuva convectiva
    gm_lookup: dict[tuple[str, str], dict[str, Any]] = {
        (g["station_id"], g["source"]): g for g in grid_matches
    }
    exploratory_stations: list[dict[str, Any]] = []
    for sid in selected_station_ids:
        st = station_by_id[sid]
        recs = records_by_station[sid]
        # Regime de chuva convectiva no verao (out-mar) nas horas validas da estacao
        summer_rain = [
            float(r.precip_mm) for r in recs
            if r.precip_mm is not None and r.ts.month in (10, 11, 12, 1, 2, 3)
        ]
        tot_rain = sum(summer_rain)
        conv_rain = sum(v for v in summer_rain if v >= 10.0)
        conv_frac = round(conv_rain / tot_rain, 4) if tot_rain > 0 else None
        elev = float(st.elevation_m) if st.elevation_m is not None else 0.0
        band = "serra_ge_900m" if elev >= 900.0 else ("planalto_500_900m" if elev >= 500.0 else "baixa_lt_500m")

        row: dict[str, Any] = {
            "station_id": sid,
            "station_name": st.station_name,
            "elevation_m": st.elevation_m,
            "elevation_band": band,
            "summer_total_rain_mm": round(tot_rain, 1),
            "convective_ge10mmh_frac": conv_frac,
            "grid_meta": {
                k: {
                    "distance_km": gm_lookup[(sid, k)]["distance_km"],
                    "elev_diff_m": gm_lookup[(sid, k)]["elev_diff_m"],
                }
                for k in ("era5_combined_t_rh_010", "era5_combined_precip_025", "historical_forecast", "nasa_power")
                if (sid, k) in gm_lookup
            },
            "mills_f1_by_source": {
                src: results_by_rule["mills_revised"][src]["per_station"].get(sid, {}).get("f1")
                for src in GRID_SOURCES
            },
            "r310_f1_by_source": {
                src: results_by_rule["rule_3_10"][src]["per_station"].get(sid, {}).get("f1")
                for src in GRID_SOURCES
            },
            "r310_far_by_source": {
                src: results_by_rule["rule_3_10"][src]["per_station"].get(sid, {}).get("far")
                for src in GRID_SOURCES
            },
        }
        exploratory_stations.append(row)

    # Correlacoes de Spearman exploratorias
    correlations: dict[str, Any] = {}
    for src, gm_key in (
        ("era5_combined", "era5_combined_precip_025"),
        ("historical_forecast", "historical_forecast"),
        ("nasa_power", "nasa_power"),
    ):
        mills_pts = [
            (r["elevation_m"], abs(r["grid_meta"][gm_key]["elev_diff_m"] or 0.0), r["convective_ge10mmh_frac"], r["mills_f1_by_source"][src])
            for r in exploratory_stations
            if r["elevation_m"] is not None and r["mills_f1_by_source"][src] is not None and r["convective_ge10mmh_frac"] is not None
        ]
        r310_pts = [
            (r["elevation_m"], abs(r["grid_meta"][gm_key]["elev_diff_m"] or 0.0), r["convective_ge10mmh_frac"], r["r310_f1_by_source"][src])
            for r in exploratory_stations
            if r["elevation_m"] is not None and r["r310_f1_by_source"][src] is not None and r["convective_ge10mmh_frac"] is not None
        ]
        correlations[src] = {
            "mills_f1_vs_station_elev": _spearman_corr([p[0] for p in mills_pts], [p[3] for p in mills_pts]),
            "mills_f1_vs_abs_elev_diff": _spearman_corr([p[1] for p in mills_pts], [p[3] for p in mills_pts]),
            "mills_f1_vs_convective_frac": _spearman_corr([p[2] for p in mills_pts], [p[3] for p in mills_pts]),
            "r310_f1_vs_station_elev": _spearman_corr([p[0] for p in r310_pts], [p[3] for p in r310_pts]),
            "r310_f1_vs_convective_frac": _spearman_corr([p[2] for p in r310_pts], [p[3] for p in r310_pts]),
        }

    # Agrupamento exploratorio por faixa altitudinal
    by_band: dict[str, dict[str, Any]] = {}
    for band in ("baixa_lt_500m", "planalto_500_900m", "serra_ge_900m"):
        sub = [r for r in exploratory_stations if r["elevation_band"] == band]
        if not sub:
            continue
        by_band[band] = {
            "n_stations": len(sub),
            "stations": [f"{r['station_id']} ({r['station_name']})" for r in sub],
            "mean_convective_frac": round(sum(r["convective_ge10mmh_frac"] for r in sub if r["convective_ge10mmh_frac"] is not None) / len(sub), 4),
            "mean_mills_f1": {
                src: (
                    round(sum(r["mills_f1_by_source"][src] for r in sub if r["mills_f1_by_source"][src] is not None) /
                          sum(1 for r in sub if r["mills_f1_by_source"][src] is not None), 4)
                    if any(r["mills_f1_by_source"][src] is not None for r in sub) else None
                )
                for src in GRID_SOURCES
            },
            "mean_r310_f1": {
                src: (
                    round(sum(r["r310_f1_by_source"][src] for r in sub if r["r310_f1_by_source"][src] is not None) /
                          sum(1 for r in sub if r["r310_f1_by_source"][src] is not None), 4)
                    if any(r["r310_f1_by_source"][src] is not None for r in sub) else None
                )
                for src in GRID_SOURCES
            },
        }

    payload = {
        "schema_version": "2.0.0",
        "frozen_tag": "v2-freeze-br",
        "inrae_portal_status": "HTTP 503 em 22 nov 2026 (conjunto confirmatorio pendente)",
        "source_labels": {
            "era5_combined": "ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5",
            "historical_forecast": "Open-Meteo Historical Forecast",
            "nasa_power": "NASA POWER (MERRA-2, UTC)",
        },
        "selection_table": selection_table,
        "selected_counts_by_crop": {
            c: {"n_stations": len(m), "n_station_seasons": sum(len(v) for v in m.values())}
            for c, m in passing_seasons_by_crop.items()
        },
        "grid_matches": grid_matches,
        "results": results_by_rule,
        "exploratory_relief_and_convective_diagnosis": {
            "label": "EXPLORATORIO",
            "stations": exploratory_stations,
            "spearman_correlations": correlations,
            "by_elevation_band": by_band,
        },
    }

    out_path = ROOT / "data" / "v2_phase4_brazil_results.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSalvo em {out_path.relative_to(ROOT)}")

    print("\n=== RESUMO FASE 4 (SANTA CATARINA, INMET) ===")
    for rule_name, crop, interp in rule_specs:
        print(f"\n[{rule_name}] ({crop}) -> {interp}")
        for src in GRID_SOURCES:
            r = results_by_rule[rule_name][src]
            pt = r["point"]
            ci = r["ci95_station_bootstrap"]
            miss = pt["missed_rate"]
            miss_ci = ci["missed_rate"] if ci else None
            far = pt["far"]
            f1 = pt["f1"]
            lag = pt["median_lag_days"]
            iqr = pt["iqr_lag_days"]
            cl = pt["cost_loss"]["by_ratio"]
            v05 = cl["0.05"]["relative_value"]
            v10 = cl["0.10"]["relative_value"]
            v20 = cl["0.20"]["relative_value"]
            print(
                f"  {src:20s} | ref={pt['n_ref']:4d} cand={pt['n_cand']:4d} | "
                f"miss={miss*100:5.1f}% CI={miss_ci} | FAR={far*100:5.1f}% | F1={f1:.3f} | "
                f"lag={lag} d {iqr} | V={v05}/{v10}/{v20}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
