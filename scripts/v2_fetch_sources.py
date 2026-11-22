#!/usr/bin/env python3
"""
scripts/v2_fetch_sources.py
===========================
Fase 2 do vitirule v2: baixa e grava em cache local (`data/v2_cache/`, fora do
Git) as series meteorologicas horarias das fontes candidatas para as estacoes
de desenvolvimento locais, registrando para cada estacao e fonte:
- distancia horizontal (Haversine, km) ate o ponto de grade
- diferenca de altitude (m, grade menos estacao), sem aplicar correcao na
  analise principal
- verificacao de cobertura e `time_standard == "UTC"` no NASA POWER

Nenhuma metrica comparativa de alertas de doenca roda neste script.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitirule_v2.sensors import discover_local_dev_stations, load_polito_records
from vitirule_v2.sources import (
    build_station_grid_match,
    fetch_era5_025_grid_meta,
    fetch_era5_combined,
    fetch_historical_forecast,
    fetch_nasa_power_hourly,
    fetch_previous_runs,
)

CACHE_DIR = ROOT / "data" / "v2_cache"


def run_fetch_phase2(output_path: Path | None = None) -> dict[str, Any]:
    stations = discover_local_dev_stations(ROOT / "data" / "lwd_sensors")
    session = requests.Session()
    grid_matches: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for st in stations:
        if st.network == "inrae":
            long_start, long_end = "2019-03-01", "2025-10-05"
            hf_start, hf_end = "2022-03-01", "2025-10-05"
            prev_years = [2024, 2025]
        else:
            recs = load_polito_records(st.path)
            yr = sorted({r.ts.year for r in recs})[0]
            long_start, long_end = f"{yr}-03-01", f"{yr}-10-05"
            hf_start, hf_end = long_start, long_end
            prev_years = [yr] if yr >= 2024 else []

        tag = f"{st.network}_{st.station_id}"
        print(f"[{st.network}] {st.station_id} ({st.name}, elev={st.elevation_m}m) ...")

        # 1. ERA5 combinado: T e UR do ERA5-Land (0,1 grau), chuva, vento e radiacao do ERA5 (0,25 grau)
        era_recs, era_meta = fetch_era5_combined(
            st.lat, st.lon, long_start, long_end, cache_dir=CACHE_DIR, station_tag=tag, session=session
        )
        grid_matches.append(
            build_station_grid_match(
                st.network, st.station_id, st.name, "era5_combined_t_rh_010",
                st.lat, st.lon, st.elevation_m,
                era_meta["grid_lat"], era_meta["grid_lon"], era_meta["grid_elev_m"],
                model_note="era5_seamless: T e UR do ERA5-Land (0,1 grau)",
            ).to_dict()
        )
        era025_meta = fetch_era5_025_grid_meta(
            st.lat, st.lon, cache_dir=CACHE_DIR, station_tag=tag, session=session
        )
        grid_matches.append(
            build_station_grid_match(
                st.network, st.station_id, st.name, "era5_combined_precip_025",
                st.lat, st.lon, st.elevation_m,
                era025_meta["grid_lat"], era025_meta["grid_lon"], era025_meta["grid_elev_m"],
                model_note="era5_seamless: chuva, vento e radiacao do ERA5 (0,25 grau)",
            ).to_dict()
        )
        coverage_rows.append({
            "network": st.network, "station_id": st.station_id, "source": "era5_combined",
            "range": f"{long_start}..{long_end}", "n_hours": len(era_recs),
            "n_valid_temp": sum(r.temp_c is not None for r in era_recs),
        })
        time.sleep(0.3)

        # 2. Historical Forecast (2022-2025)
        hf_recs, hf_meta = fetch_historical_forecast(
            st.lat, st.lon, hf_start, hf_end, model="best_match",
            cache_dir=CACHE_DIR, station_tag=tag, session=session
        )
        grid_matches.append(
            build_station_grid_match(
                st.network, st.station_id, st.name, "historical_forecast",
                st.lat, st.lon, st.elevation_m,
                hf_meta["grid_lat"], hf_meta["grid_lon"], hf_meta["grid_elev_m"],
                model_note=str(hf_meta.get("model", "")),
            ).to_dict()
        )
        coverage_rows.append({
            "network": st.network, "station_id": st.station_id, "source": "historical_forecast",
            "range": f"{hf_start}..{hf_end}", "n_hours": len(hf_recs),
            "n_valid_temp": sum(r.temp_c is not None for r in hf_recs),
        })
        time.sleep(0.3)

        # 3. Previous Runs (2024-2025, lead days 1-3)
        for pyr in prev_years:
            p_start, p_end = f"{pyr}-03-01", f"{pyr}-10-05"
            pr_by_lead, pr_meta = fetch_previous_runs(
                st.lat, st.lon, p_start, p_end, lead_days=(1, 2, 3),
                cache_dir=CACHE_DIR, station_tag=f"{tag}_{pyr}", session=session
            )
            if pyr == prev_years[0]:
                grid_matches.append(
                    build_station_grid_match(
                        st.network, st.station_id, st.name, "previous_runs",
                        st.lat, st.lon, st.elevation_m,
                        pr_meta["grid_lat"], pr_meta["grid_lon"], pr_meta["grid_elev_m"],
                        model_note="previous_day1,2,3",
                    ).to_dict()
                )
            coverage_rows.append({
                "network": st.network, "station_id": st.station_id, "source": f"previous_runs_{pyr}",
                "range": f"{p_start}..{p_end}",
                "n_hours_day1": len(pr_by_lead[1]),
                "n_valid_day1": sum(r.temp_c is not None for r in pr_by_lead[1]),
                "n_valid_day3": sum(r.temp_c is not None for r in pr_by_lead[3]),
            })
            time.sleep(0.3)

        # 4. NASA POWER hourly (explicit time-standard=UTC), baixado por ano para evitar limites da API
        yr_start_i = int(long_start[:4])
        yr_end_i = int(long_end[:4])
        nasa_total = 0
        nasa_valid_t = 0
        nasa_meta_saved = None
        for nyr in range(yr_start_i, yr_end_i + 1):
            n_recs, n_meta = fetch_nasa_power_hourly(
                st.lat, st.lon, f"{nyr}-03-01", f"{nyr}-10-05",
                cache_dir=CACHE_DIR, station_tag=f"{tag}_{nyr}", session=session
            )
            nasa_total += len(n_recs)
            nasa_valid_t += sum(r.temp_c is not None for r in n_recs)
            if nasa_meta_saved is None:
                nasa_meta_saved = n_meta
            time.sleep(0.3)

        assert nasa_meta_saved is not None
        grid_matches.append(
            build_station_grid_match(
                st.network, st.station_id, st.name, "nasa_power",
                st.lat, st.lon, st.elevation_m,
                nasa_meta_saved["grid_lat"], nasa_meta_saved["grid_lon"], nasa_meta_saved["grid_elev_m"],
                model_note=f"{nasa_meta_saved['model']} (time_standard={nasa_meta_saved['time_standard']})",
            ).to_dict()
        )
        coverage_rows.append({
            "network": st.network, "station_id": st.station_id, "source": "nasa_power",
            "range": f"{yr_start_i}..{yr_end_i}", "n_hours": nasa_total, "n_valid_temp": nasa_valid_t,
        })

    payload = {
        "schema_version": "2.0.0",
        "note": "Metadados de distancia e diferenca de altitude entre estacoes locais e pontos de grade das fontes candidatas. Nenhuma correcao de altitude aplicada.",
        "grid_matches": grid_matches,
        "coverage": coverage_rows,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    out = ROOT / "data" / "v2_phase2_grid_metadata.json"
    res = run_fetch_phase2(output_path=out)
    print("\n=== DISTANCIA E DIFERENCA DE ALTITUDE (GRADE - ESTACAO) ===")
    for g in res["grid_matches"]:
        print(
            f"  [{g['network']:6s}] {g['station_id']:8s} | {g['source']:19s} | "
            f"dist={g['distance_km']:6.2f} km | st_elev={g['station_elev_m']}m | "
            f"grid_elev={g['grid_elev_m']}m | diff={g['elev_diff_m']}m"
        )
    print(f"\nSalvo em {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
